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

# --- 3. LÓGICA DE BASE DE DATOS ---

@st.cache_data(ttl=60)
def cargar_db(tabla):
    res = supabase.table(tabla).select("*").execute()
    return pd.DataFrame(res.data)

def guardar_campo(nombre, c11, c7):
    supabase.table("campos").upsert({"nombre": nombre, "capacidad_f11": c11, "capacidad_f7": c7}, on_conflict="nombre").execute()
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

# --- 5. PÁGINA: VALIDACIÓN ---

def pagina_validacion():
    st.title("🔍 Validación de Horarios Inteligente")
    
    with st.sidebar:
        st.header("Configuración")
        tipo_global = st.radio("Tipo de partidos en el CSV:", ["F11", "F7"])
        duracion_defecto = st.number_input("Duración por defecto (si no hay categoría):", value=105)

    archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])
    
    if archivo:
        try:
            # Carga de CSV y DB
            df_db_campos = cargar_db("campos")
            df_db_cats = cargar_db("categorias")
            
            try:
                df = pd.read_csv(archivo, sep=';', encoding='utf-8')
            except:
                archivo.seek(0)
                df = pd.read_csv(archivo, sep=';', encoding='latin-1')
            
            df.columns = df.columns.str.strip()
            df['Campo'] = df['Campo'].astype(str).str.strip()
            df['Tipo'] = tipo_global

            # Función para calcular el fin según categoría
            def obtener_fin(fila):
                info_comp = normalizar_texto(fila.get('Competición', ''))
                minutos = duracion_defecto
                for _, cat in df_db_cats.iterrows():
                    if normalizar_texto(cat['palabra_clave']) in info_comp:
                        minutos = cat['duracion_minutos']
                        break
                inicio = pd.to_datetime(fila['Fecha'] + ' ' + fila['Hora'], dayfirst=True)
                return inicio + timedelta(minutes=minutos)

            # Preparar datos
            df_val = pd.merge(df, df_db_campos, left_on='Campo', right_on='nombre', how='left')
            df_val['capacidad_f11'] = df_val['capacidad_f11'].fillna(0)
            df_val['capacidad_f7'] = df_val['capacidad_f7'].fillna(0)
            df_val['Inicio'] = pd.to_datetime(df_val['Fecha'] + ' ' + df_val['Hora'], dayfirst=True)
            df_val['Fin'] = df_val.apply(obtener_fin, axis=1)

            conflictos = []
            for campo in df_val['Campo'].unique():
                df_c = df_val[df_val['Campo'] == campo].sort_values('Inicio')
                c11_m, c7_m = int(df_c['capacidad_f11'].iloc[0]), int(df_c['capacidad_f7'].iloc[0])
                
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

                    if (nf11 > c11_m) or (nf11 >= 1 and nf7 > 0) or (nf11 == 0 and nf7 > c7_m):
                        if activos: conflictos.append({"campo": campo, "c11": c11_m, "c7": c7_m, "hora": t.strftime('%H:%M'), "activos": list(activos)})

            # Renderizado
            if conflictos:
                vistos = set()
                for i, c in enumerate(conflictos):
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if (c['campo'], ids) not in vistos:
                        vistos.add((c['campo'], ids))
                        with st.expander(f"⚠️ {c['campo']} | Conflicto {c['hora']} (Capacidad F11:{c['c11']} F7:{c['c7']})", expanded=False):
                            c1, c2 = st.columns([0.8, 0.2])
                            c1.write(f"Solapamiento detectado entre {len(c['activos'])} partidos:")
                            if c2.button("📝 Ajustar", key=f"btn_{i}"): modal_campo(c['campo'], c['c11'], c['c7'])
                            for p in c['activos']:
                                b = "badge-f11" if p['Tipo'] == "F11" else "badge-f7"
                                st.markdown(f"<div class='match-box'><span class='match-text'><span class='code-badge'>{p.get('Código Partido','S/C')}</span><b>{p['Hora']}</b>: {p['Equipo Casa']} vs {p['Equipo Visitante']}</span><span class='{b}'>{p['Tipo']}</span></div>", unsafe_allow_html=True)
            else:
                st.success("✅ Todo correcto. Los horarios respetan las capacidades por categoría.")
        except Exception as e:
            st.error(f"Error procesando el archivo: {e}")

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
