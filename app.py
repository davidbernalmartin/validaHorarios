import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client

# --- 1. CONFIGURACIÓN Y CONEXIÓN ---
st.set_page_config(page_title="Validador Pro ⚽", layout="wide", page_icon="⚽")

# Acceso seguro a credenciales
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Error de configuración de Secrets. Verifica SUPABASE_URL y SUPABASE_KEY.")
    st.stop()

# --- 2. ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
    <style>
    .conflict-card { 
        background-color: #fdf2f2; 
        border-left: 5px solid #ff4b4b; 
        padding: 18px; 
        border-radius: 10px; 
        margin-bottom: 25px;
        border: 1px solid #ffcccc;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.03);
    }
    .match-info { 
        font-size: 14px; margin: 6px 0; padding: 10px; 
        background-color: white; border-radius: 6px; 
        border: 1px solid #eee;
        display: flex;
        justify-content: space-between;
    }
    .badge-f11 { background: #1f77b4; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .badge-f7 { background: #2ca02c; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .code-badge { background: #f0f2f6; color: #555; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 3. LÓGICA DE BASE DE DATOS ---

@st.cache_data(ttl=60)
def obtener_datos_campos():
    try:
        res = supabase.table("campos").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7'])

def upsert_campo(nombre, c11, c7):
    data = {
        "nombre": str(nombre).strip(),
        "capacidad_f11": int(c11),
        "capacidad_f7": int(c7)
    }
    supabase.table("campos").upsert(data, on_conflict="nombre").execute()
    st.cache_data.clear()

# --- 4. DIÁLOGOS (MODALES) ---

@st.dialog("Configurar Instalación")
def editar_campo_dialog(nombre_campo, c11_actual=0, c7_actual=0):
    st.write(f"Ajustando capacidades para: **{nombre_campo}**")
    st.info("Si el campo es nuevo, se guardará por primera vez.")
    new_c11 = st.number_input("Capacidad F11", min_value=0, value=int(c11_actual))
    new_c7 = st.number_input("Capacidad F7", min_value=0, value=int(c7_actual))
    
    if st.button("💾 Guardar en Supabase"):
        upsert_campo(nombre_campo, new_c11, new_c7)
        st.success("¡Datos actualizados!")
        st.rerun()

# --- 5. PÁGINA: VALIDACIÓN DE PARTIDOS (ACTUALIZADA CON CONTRASTE Y EXPANDERS) ---
def pagina_validacion():
    st.title("🔍 Validación de Horarios y Solapamientos")
    
    with st.sidebar:
        st.header("⚙️ Parámetros")
        tipo_fichero = st.radio("Tipo de partidos:", ["F11", "F7"])
        st.divider()
        duracion = st.number_input("Duración partido (min):", min_value=1, value=105)

    archivo = st.file_uploader(f"Sube el CSV de partidos ({tipo_fichero})", type=['csv'])
    
    if archivo:
        try:
            # Lectura del CSV (omito la parte de carga por brevedad, es igual a la anterior)
            try:
                df_raw = pd.read_csv(archivo, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                archivo.seek(0)
                df_raw = pd.read_csv(archivo, sep=';', encoding='latin-1')
            
            df_raw.columns = df_raw.columns.str.strip()
            df_raw['Campo'] = df_raw['Campo'].astype(str).str.strip()
            df_raw['Tipo'] = tipo_fichero 
            
            df_db = obtener_datos_campos()
            df_merge = pd.merge(df_raw, df_db, left_on='Campo', right_on='nombre', how='left')
            df_merge['capacidad_f11'] = df_merge['capacidad_f11'].fillna(0)
            df_merge['capacidad_f7'] = df_merge['capacidad_f7'].fillna(0)
            df_merge['Inicio'] = pd.to_datetime(df_merge['Fecha'] + ' ' + df_merge['Hora'], dayfirst=True, errors='coerce')
            df_merge = df_merge.dropna(subset=['Inicio'])
            df_merge['Fin'] = df_merge['Inicio'] + timedelta(minutes=duracion)

            # --- Lógica de detección de conflictos ---
            conflictos = []
            for campo in df_merge['Campo'].unique():
                df_c = df_merge[df_merge['Campo'] == campo]
                c11_max, c7_max = int(df_c['capacidad_f11'].iloc[0]), int(df_c['capacidad_f7'].iloc[0])
                
                eventos = []
                for _, p in df_c.iterrows():
                    eventos.append((p['Inicio'], 1, p))
                    eventos.append((p['Fin'], -1, p))
                
                eventos.sort(key=lambda x: (x[0], x[1]))
                activos = []
                for tiempo, tipo, p_data in eventos:
                    if tipo == 1: activos.append(p_data)
                    else:
                        id_p = str(p_data.get('Código Partido', ''))
                        activos = [p for p in activos if str(p.get('Código Partido', '')) != id_p]

                    n_f11 = len([p for p in activos if str(p.get('Tipo')).upper() == 'F11'])
                    n_f7 = len([p for p in activos if str(p.get('Tipo')).upper() == 'F7'])

                    if (n_f11 > c11_max) or (n_f11 >= 1 and n_f7 > 0) or (n_f11 == 0 and n_f7 > c7_max):
                        if len(activos) > 0:
                            conflictos.append({"campo": campo, "c11": c11_max, "c7": c7_max, "hora": tiempo.strftime('%H:%M'), "activos": list(activos)})

            # --- RENDERIZADO CON EXPANDERS Y CONTRASTE ---
            st.subheader("Análisis de Capacidades")
            if conflictos:
                vistos = set()
                for i, c in enumerate(conflictos):
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if (c['campo'], ids) not in vistos:
                        vistos.add((c['campo'], ids))
                        
                        # Título del expander con información clave
                        titulo_error = f"⚠️ {c['campo']} | Bloqueo a las {c['hora']} (F11:{c['c11']} F7:{c['c7']})"
                        
                        with st.expander(titulo_error, expanded=False):
                            col_tit, col_btn = st.columns([0.8, 0.2])
                            with col_tit:
                                st.write(f"Hay **{len(c['activos'])} partidos** coincidiendo en este tramo.")
                            with col_btn:
                                if st.button("📝 Ajustar Campo", key=f"ed_{c['campo']}_{i}"):
                                    editar_campo_dialog(c['campo'], c['c11'], c['c7'])
                            
                            for p in c['activos']:
                                badge = "badge-f11" if p['Tipo'] == "F11" else "badge-f7"
                                # Estilo con fondo gris claro y texto oscuro para máximo contraste
                                st.markdown(f"""
                                    <div style="background-color: #f0f2f6; padding: 10px; border-radius: 8px; margin-bottom: 8px; border: 1px solid #d1d5db; display: flex; justify-content: space-between; align-items: center;">
                                        <span style="color: #1f2937; font-weight: 500;">
                                            <span class='code-badge' style="color: #4b5563;">{p.get('Código Partido', 'S/C')}</span> 
                                            <b style="color: #000;">{p['Hora']}</b>: {p['Equipo Casa']} vs {p['Equipo Visitante']}
                                        </span>
                                        <span class='{badge}'>{p['Tipo']}</span>
                                    </div>
                                """, unsafe_allow_html=True)
            else:
                st.success(f"✅ Sin conflictos en {tipo_fichero}.")

        except Exception as e:
            st.error(f"Error: {e}")

# --- 6. PÁGINA: MAESTRO DE CAMPOS ---

def pagina_gestion():
    st.title("🏟️ Maestro de Instalaciones")
    st.info("Gestiona la base de datos global de Supabase.")
    
    df_db = obtener_datos_campos()
    
    st.subheader("Edición Manual")
    df_editado = st.data_editor(
        df_db[['nombre', 'capacidad_f11', 'capacidad_f7']], 
        num_rows="dynamic", 
        use_container_width=True, 
        hide_index=True,
        key="main_editor"
    )
    
    if st.button("💾 Sincronizar Cambios con Supabase"):
        with st.spinner("Guardando..."):
            for _, f in df_editado.iterrows():
                upsert_campo(f['nombre'], f['capacidad_f11'], f['capacidad_f7'])
            st.success("¡Base de datos actualizada!")
            st.rerun()

# --- 7. NAVEGACIÓN ---

pg = st.navigation([
    st.Page(pagina_validacion, title="Validador", icon="🔍"),
    st.Page(pagina_gestion, title="Maestro de Campos", icon="🏟️"),
])
pg.run()
