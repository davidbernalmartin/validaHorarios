import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client
import unicodedata

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
st.set_page_config(page_title="Gestor Pro Fútbol Base", layout="wide", page_icon="⚽")

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Error: Configura SUPABASE_URL y SUPABASE_KEY en los Secrets de Streamlit.")
    st.stop()

# --- 2. FUNCIONES DE APOYO Y CSS ---
def normalizar_texto(texto):
    """Elimina tildes y pasa a mayúsculas para comparaciones precisas."""
    if pd.isna(texto): return ""
    texto = ''.join((c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn'))
    return texto.upper().strip()

st.markdown("""
    <style>
    .conflict-card { background-color: #1e1e1e; border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #333; }
    .match-box { background-color: #f0f2f6; padding: 10px; border-radius: 8px; margin-bottom: 8px; border: 1px solid #d1d5db; display: flex; justify-content: space-between; align-items: center; }
    .match-text { color: #1f2937; font-weight: 500; }
    .badge-f11 { background: #1f77b4; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .badge-f7 { background: #2ca02c; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .code-badge { background: #e5e7eb; color: #4b5563; padding: 2px 6px; border-radius: 4px; font-family: monospace; margin-right: 5px; }
    </style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def cargar_db(tabla):
    try:
        res = supabase.table(tabla).select("*").execute()
        df = pd.DataFrame(res.data)
        if df.empty:
            if tabla == "campos": return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7', 'capacidad_debutante'])
            if tabla == "categorias": return pd.DataFrame(columns=['palabra_clave', 'duracion_minutos'])
        return df
    except:
        if tabla == "campos": return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7', 'capacidad_debutante'])
        return pd.DataFrame(columns=['palabra_clave', 'duracion_minutos'])

def guardar_campo(nombre, capacidad):
    supabase.table("campos").upsert({
        "nombre": nombre, 
        "capacidad_total": float(capacidad)
    }, on_conflict="nombre").execute()
    st.cache_data.clear()

# --- 4. DIÁLOGOS ---

@st.dialog("Configurar Instalación")
def modal_campo(nombre, c11=0, c7=0):
    st.write(f"Campo: **{nombre}**")
    nc11 = st.number_input("Capacidad F11", min_value=0, value=int(c11))
    nc7 = st.number_input("Capacidad F7", min_value=0, value=int(c7))
    if st.button("Guardar"):
        guardar_campo(nombre, nc11, nc7)
        st.rerun()

def pagina_categorias():
    st.title("⏱️ Gestión de Categorías y Espacios")
    st.info("Define la palabra clave, el tiempo de ocupación y el tipo de campo que utiliza.")
    
    df = cargar_db("categorias")
    
    # Aseguramos que las columnas existen para el editor
    for col in ['palabra_clave', 'duracion_minutos', 'tipo_campo']:
        if col not in df.columns: df[col] = None

    ed = st.data_editor(
        df[['palabra_clave', 'duracion_minutos', 'tipo_campo']], 
        num_rows="dynamic", 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "tipo_campo": st.column_config.SelectboxColumn(
                "Tipo de Campo",
                options=["F11", "F7", "Debutante"],
                required=True,
            )
        }
    )
    
    if st.button("💾 Guardar Configuración"):
        df_save = ed.dropna(subset=['palabra_clave'])
        for _, f in df_save.iterrows():
            supabase.table("categorias").upsert({
                "palabra_clave": normalizar_texto(f['palabra_clave']), 
                "duracion_minutos": int(f['duracion_minutos']),
                "tipo_campo": f['tipo_campo']
            }, on_conflict="palabra_clave").execute()
        st.success("Configuración actualizada.")
        st.cache_data.clear()
        st.rerun()

def pagina_validacion():
    st.title("🔍 Validador Automático Multicategoría")
    
    with st.sidebar:
        st.header("Ajustes de Emergencia")
        st.info("Estos valores se usan solo si la competición no coincide con ninguna categoría de la base de datos.")
        tipo_emergencia = st.selectbox("Tipo por defecto:", ["F11", "F7", "Debutante"])
        duracion_defecto = st.number_input("Duración por defecto (min):", value=105)

    archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])
    
    if archivo:
        try:
            # 1. Carga de configuraciones desde DB
            df_db_campos = cargar_db("campos")
            df_db_cats = cargar_db("categorias")
            
            # Ordenamos categorías por longitud (descendente) para evitar conflictos (ej: PREBENJAMIN vs BENJAMIN)
            if not df_db_cats.empty:
                df_db_cats['longitud'] = df_db_cats['palabra_clave'].str.len()
                df_db_cats = df_db_cats.sort_values(by='longitud', ascending=False)
            
            # 2. Lectura del CSV
            try:
                df = pd.read_csv(archivo, sep=';', encoding='utf-8')
            except:
                archivo.seek(0)
                df = pd.read_csv(archivo, sep=';', encoding='latin-1')
            
            df.columns = df.columns.str.strip()
            df['Campo'] = df['Campo'].astype(str).str.strip()

            # 3. LÓGICA DE DETECCIÓN INTELIGENTE (Tiempo y Tipo de Espacio)
            def detectar_parametros(fila):
                info_comp = normalizar_texto(fila.get('Competición', ''))
                
                # Valores iniciales (emergencia)
                minutos = duracion_defecto
                tipo_espacio = tipo_emergencia
                
                # Buscamos en la tabla de categorías
                for _, cat in df_db_cats.iterrows():
                    if normalizar_texto(cat['palabra_clave']) in info_comp:
                        minutos = cat['duracion_minutos']
                        tipo_espacio = cat.get('tipo_campo', 'F11') # F11 por defecto si la columna no existe
                        break
                
                # Procesamiento de fechas para evitar errores de concatenación
                f_val = str(fila['Fecha']).strip().lower()
                h_val = str(fila['Hora']).strip().lower()
                
                if f_val == "nan" or h_val == "nan" or not f_val or not h_val:
                    return pd.Series([pd.NaT, pd.NaT, tipo_espacio, True])
                
                inicio = pd.to_datetime(f_val + ' ' + h_val, dayfirst=True, errors='coerce')
                fin = inicio + timedelta(minutes=minutos) if pd.notna(inicio) else pd.NaT
                
                return pd.Series([inicio, fin, tipo_espacio, pd.isna(inicio)])

            # Aplicamos la detección a todo el DataFrame
            df[['Inicio', 'Fin', 'Tipo', 'Error_Horario']] = df.apply(detectar_parametros, axis=1)
            
            # 4. Cruce con Capacidad de Campos
            df_val = pd.merge(df, df_db_campos, left_on='Campo', right_on='nombre', how='left')
            df_val['capacidad_f11'] = df_val['capacidad_f11'].fillna(0)
            
            # 5. Render de Alertas Críticas (Partidos sin fecha/hora)
            partidos_con_error = df_val[df_val['Error_Horario'] == True]
            if not partidos_con_error.empty:
                st.error(f"🚨 Se han detectado {len(partidos_con_error)} partidos con datos de horario incompletos:")
                for _, p in partidos_con_error.iterrows():
                    st.warning(f"**ID: {p.get('Código Partido', 'S/C')}** | {p['Equipo Casa']} vs {p['Equipo Visitante']} (Campo: {p['Campo']})")
                st.divider()

            # Quitamos errores para el algoritmo
            df_clean = df_val.dropna(subset=['Inicio', 'Fin']).copy()

            # 6. ALGORITMO DE FRACCIONES DE ESPACIO (Matemático)
            conflictos = []
            for campo in df_clean['Campo'].unique():
                df_c = df_clean[df_clean['Campo'] == campo].sort_values('Inicio')
                num_campos_f11 = int(df_c['capacidad_f11'].iloc[0])
                
                eventos = []
                for _, p in df_c.iterrows():
                    eventos.append((p['Inicio'], 1, p))
                    eventos.append((p['Fin'], -1, p))
                
                # Ordenar por tiempo; si coincide, salidas (-1) antes que entradas (1)
                eventos.sort(key=lambda x: (x[0], x[1]))
                
                activos = []
                for t, estado, p_data in eventos:
                    if estado == 1: 
                        activos.append(p_data)
                    else:
                        id_p = str(p_data.get('Código Partido', ''))
                        activos = [p for p in activos if str(p.get('Código Partido', '')) != id_p]

                    # 1. Contamos activos por tipo
                    nf11 = len([p for p in activos if p['Tipo'] == "F11"])
                    nf7 = len([p for p in activos if p['Tipo'] == "F7"])
                    ndeb = len([p for p in activos if p['Tipo'] == "Debutante"])
                    
                    # 2. Obtenemos la capacidad total de la instalación (ej: 1.5)
                    cap_max = float(df_c['capacidad_total'].iloc[0])
                    
                    # 3. Sumamos el consumo de espacio
                    # F11 (1.0) | F7 (0.5) | Debutante (0.25)
                    consumo_actual = (nf11 * 1.0) + (nf7 * 0.5) + (ndeb * 0.25)
                    
                    # 4. Verificamos conflicto
                    if consumo_actual > cap_max:
                        conflictos.append({
                            "campo": campo, 
                            "cap": cap_max, 
                            "uso": consumo_actual,
                            "hora": t.strftime('%H:%M'), 
                            "activos": list(activos)
                        })

            # 7. RENDERIZADO DE RESULTADOS
            st.subheader("Análisis de Ocupación Real")
            if conflictos:
                vistos = set()
                for i, c in enumerate(conflictos):
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if (c['campo'], ids) not in vistos:
                        vistos.add((c['campo'], ids))
                        
                        with st.expander(f"⚠️ {c['campo']} | Sobreocupación a las {c['hora']}", expanded=False):
                            c1, c2 = st.columns([0.8, 0.2])
                            c1.markdown(f"Capacidad: **{c['cap']} campos F11** | Ocupación: **{c['uso']}**")
                            if c2.button("📝 Ajustar Capacidad", key=f"btn_v_{i}"):
                                modal_campo(c['campo'], c['cap'])
                            
                            for p in c['activos']:
                                # Selección de badge según el tipo autodetectado
                                b = "badge-f11" if p['Tipo'] == "F11" else ("badge-f7" if p['Tipo'] == "F7" else "badge-deb")
                                st.markdown(f"""
                                    <div class='match-box'>
                                        <span class='match-text'>
                                            <span class='code-badge'>{p.get('Código Partido','S/C')}</span>
                                            <b>{p['Hora']}</b>: {p['Equipo Casa']} vs {p['Equipo Visitante']}
                                        </span>
                                        <span class='{b}'>{p['Tipo']}</span>
                                    </div>
                                """, unsafe_allow_html=True)
            elif partidos_con_error.empty:
                st.success("✅ Validación completada: Todos los partidos encajan perfectamente en los campos asignados.")
            else:
                st.info("No hay solapamientos, pero revisa los partidos con datos incompletos arriba.")

        except Exception as e:
            st.error(f"Error crítico en la validación: {e}")

def pagina_campos():
    st.title("🏟️ Maestro de Instalaciones")
    df = cargar_db("campos")
    # Aseguramos que la columna existe
    if 'capacidad_total' not in df.columns: df['capacidad_total'] = 1.0
    
    ed = st.data_editor(df[['nombre', 'capacidad_total']], num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Guardar Cambios"):
        for _, f in ed.iterrows(): 
            guardar_campo(f['nombre'], f['capacidad_total'])
        st.success("Capacidades actualizadas.")

# --- 7. PÁGINA: GESTIÓN DE CATEGORÍAS ---
def pagina_categorias():
    st.title("⏱️ Tiempos por Categoría")
    st.info("Define qué palabras buscar en 'Competición' y su duración (ej: ALEVIN -> 65).")
    df = cargar_db("categorias")
    ed = st.data_editor(df[['palabra_clave', 'duracion_minutos']], num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Guardar Tiempos"):
        for _, f in ed.iterrows():
            supabase.table("categorias").upsert({"palabra_clave": normalizar_texto(f['palabra_clave']), "duracion_minutos": int(f['duracion_minutos'])}, on_conflict="palabra_clave").execute()
        st.success("Tiempos actualizados.")
        st.cache_data.clear()

# --- 8. NAVEGACIÓN ---
pg = st.navigation([
    st.Page(pagina_validacion, title="Validador", icon="🔍"),
    st.Page(pagina_campos, title="Campos", icon="🏟️"),
    st.Page(pagina_categorias, title="Categorías/Tiempos", icon="⏱️"),
])
pg.run()
