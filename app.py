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

def guardar_campo(nombre, c11, c7, cdeb):
    supabase.table("campos").upsert({
        "nombre": nombre, 
        "capacidad_f11": c11, 
        "capacidad_f7": c7,
        "capacidad_debutante": cdeb
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

def pagina_validacion():
    st.title("🔍 Validación de Horarios Inteligente")
    
    with st.sidebar:
        st.header("Configuración")
        tipo_global = st.radio("Tipo de partidos en el CSV:", ["F11", "F7", "Debutante"])
        duracion_defecto = st.number_input("Duración por defecto (min):", value=105)

    archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])
    
    if archivo:
        try:
            df_db_campos = cargar_db("campos")
            df_db_cats = cargar_db("categorias")
            
            # Ordenar categorías por longitud para evitar solapamientos de nombres (Prebenjamín/Benjamín)
            if not df_db_cats.empty:
                df_db_cats['longitud'] = df_db_cats['palabra_clave'].str.len()
                df_db_cats = df_db_cats.sort_values(by='longitud', ascending=False)
            
            df = pd.read_csv(archivo, sep=';', encoding='latin-1') # Cambiar a utf-8 si falla
            df.columns = df.columns.str.strip()
            df['Campo'] = df['Campo'].astype(str).str.strip()
            df['Tipo'] = tipo_global

            # Detección de errores de fecha/hora
            df['Error_Horario'] = (
                df['Fecha'].isna() | (df['Fecha'].astype(str).str.strip().str.lower() == 'nan') |
                df['Hora'].isna() | (df['Hora'].astype(str).str.strip().str.lower() == 'nan')
            )
            
            partidos_con_error = df[df['Error_Horario']].copy()

            def obtener_fin(fila):
                if fila['Error_Horario']: return pd.NaT
                info_comp = normalizar_texto(fila.get('Competición', ''))
                minutos = duracion_defecto
                for _, cat in df_db_cats.iterrows():
                    if normalizar_texto(cat['palabra_clave']) in info_comp:
                        minutos = cat['duracion_minutos']
                        break
                inicio = pd.to_datetime(str(fila['Fecha']) + ' ' + str(fila['Hora']), dayfirst=True, errors='coerce')
                return inicio + timedelta(minutes=minutos) if pd.notna(inicio) else pd.NaT

            df_val = pd.merge(df, df_db_campos, left_on='Campo', right_on='nombre', how='left')
            df_val['capacidad_f11'] = df_val['capacidad_f11'].fillna(0)
            df_val['Inicio'] = pd.to_datetime(df_val['Fecha'].astype(str) + ' ' + df_val['Hora'].astype(str), dayfirst=True, errors='coerce')
            df_val['Fin'] = df_val.apply(obtener_fin, axis=1)
            df_clean = df_val.dropna(subset=['Inicio', 'Fin']).copy()

            # Render Alertas
            if not partidos_con_error.empty:
                st.error(f"🚨 {len(partidos_con_error)} partidos sin horario definido.")
                st.divider()

            # Algoritmo de Fracciones de Espacio
            conflictos = []
            for campo in df_clean['Campo'].unique():
                df_c = df_clean[df_clean['Campo'] == campo].sort_values('Inicio')
                num_campos_fisicos = int(df_c['capacidad_f11'].iloc[0])
                
                eventos = []
                for _, p in df_c.iterrows():
                    eventos.append((p['Inicio'], 1, p))
                    eventos.append((p['Fin'], -1, p))
                eventos.sort(key=lambda x: (x[0], x[1]))
                
                activos = []
                for t, tipo, p_data in eventos:
                    if tipo == 1: activos.append(p_data)
                    else:
                        id_p = str(p_data.get('Código Partido', ''))
                        activos = [p for p in activos if str(p.get('Código Partido', '')) != id_p]

                    nf11 = len([p for p in activos if p['Tipo'] == "F11"])
                    nf7 = len([p for p in activos if p['Tipo'] == "F7"])
                    ndeb = len([p for p in activos if p['Tipo'] == "Debutante"])

                    # Cálculo matemático: F11=1, F7=0.5, Deb=0.25
                    consumo = (nf11 * 1.0) + (nf7 * 0.5) + (ndeb * 0.25)

                    if consumo > num_campos_fisicos and activos:
                        conflictos.append({
                            "campo": campo, "cap": num_campos_fisicos, "uso": consumo,
                            "hora": t.strftime('%H:%M'), "activos": list(activos)
                        })

            # Render Conflictos
            st.subheader("Análisis de Ocupación")
            if conflictos:
                vistos = set()
                for i, c in enumerate(conflictos):
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if (c['campo'], ids) not in vistos:
                        vistos.add((c['campo'], ids))
                        with st.expander(f"⚠️ {c['campo']} | Exceso de ocupación a las {c['hora']}", expanded=False):
                            c1, c2 = st.columns([0.8, 0.2])
                            c1.markdown(f"Capacidad: **{c['cap']} campos F11** | Ocupación actual: **{c['uso']}**")
                            if c2.button("📝 Ajustar", key=f"v_btn_{i}"): modal_campo(c['campo'], c['cap'])
                            
                            for p in c['activos']:
                                b = "badge-f11" if p['Tipo'] == "F11" else ("badge-f7" if p['Tipo'] == "F7" else "badge-deb")
                                st.markdown(f"""
                                    <div class='match-box'>
                                        <span class='match-text'><span class='code-badge'>{p.get('Código Partido','S/C')}</span><b>{p['Hora']}</b>: {p['Equipo Casa']} vs {p['Equipo Visitante']}</span>
                                        <span class='{b}'>{p['Tipo']}</span>
                                    </div>
                                """, unsafe_allow_html=True)
            else:
                st.success("✅ Todo correcto. Los solapamientos respetan la capacidad física.")

        except Exception as e:
            st.error(f"Error crítico: {e}")

# --- 6. PÁGINA: GESTIÓN DE CAMPOS ---
def pagina_campos():
    st.title("🏟️ Maestro de Campos")
    df = cargar_db("campos")
    ed = st.data_editor(df[['nombre', 'capacidad_f11', 'capacidad_f7']], num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Guardar Cambios"):
        for _, f in ed.iterrows(): guardar_campo(f['nombre'], f['capacidad_f11'], f['capacidad_f7'])
        st.success("Base de datos de campos actualizada.")

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
