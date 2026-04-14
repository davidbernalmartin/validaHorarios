import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client

# --- CONEXIÓN SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Validador Pro ⚽", layout="wide")

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    .conflict-card { 
        background-color: #fdf2f2; 
        border-left: 5px solid #ff4b4b; 
        padding: 15px; 
        border-radius: 10px; 
        margin-bottom: 20px;
        border: 1px solid #ffcccc;
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }
    .match-info { 
        font-size: 14px; margin: 5px 0; padding: 8px; 
        background-color: white; border-radius: 5px; 
        border: 1px solid #eee;
    }
    .badge-f11 { background: #1f77b4; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .badge-f7 { background: #2ca02c; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .code-badge { background: #f0f2f6; color: #555; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIONES DB ---
def obtener_datos_campos():
    try:
        res = supabase.table("campos").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7'])

# --- DIÁLOGO DE EDICIÓN RÁPIDA ---
@st.dialog("Configurar Instalación")
def editar_campo_dialog(nombre_campo, c11_actual=0, c7_actual=0):
    st.write(f"Ajustando capacidades para: **{nombre_campo}**")
    new_c11 = st.number_input("Capacidad F11", min_value=0, value=int(c11_actual))
    new_c7 = st.number_input("Capacidad F7", min_value=0, value=int(c7_actual))
    
    if st.button("Actualizar Base de Datos"):
        supabase.table("campos").upsert({
            "nombre": nombre_campo,
            "capacidad_f11": new_c11,
            "capacidad_f7": new_c7
        }, on_conflict="nombre").execute()
        st.cache_data.clear()
        st.success("Guardado correctamente")
        st.rerun()

# --- PÁGINA DE VALIDACIÓN ---
def pagina_validacion():
    st.title("🔍 Validación y Ajuste de Horarios")
    
    with st.sidebar:
        duracion = st.number_input("Duración partido (min):", value=105)
    
    archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])
    
    if archivo:
        try:
            # 1. Carga y Limpieza
            df_raw = pd.read_csv(archivo, sep=';', encoding='latin-1')
            df_raw.columns = df_raw.columns.str.strip()
            df_raw['Campo'] = df_raw['Campo'].astype(str).str.strip()
            
            # 2. Cruce con DB (Campos desconocidos tendrán NaN)
            df_db = obtener_datos_campos()
            df_merge = pd.merge(df_raw, df_db, left_on='Campo', right_on='nombre', how='left')
            
            # Tratamos NaN como capacidad 0
            df_merge['capacidad_f11'] = df_merge['capacidad_f11'].fillna(0)
            df_merge['capacidad_f7'] = df_merge['capacidad_f7'].fillna(0)
            
            # 3. Preparación de Tiempos
            df_merge['Inicio'] = pd.to_datetime(df_merge['Fecha'] + ' ' + df_merge['Hora'], dayfirst=True, errors='coerce')
            df_merge = df_merge.dropna(subset=['Inicio'])
            df_merge['Fin'] = df_merge['Inicio'] + timedelta(minutes=duracion)

            # 4. Lógica de Solapamientos
            conflictos = []
            for campo in df_merge['Campo'].unique():
                df_c = df_merge[df_merge['Campo'] == campo]
                
                # Capacidades (tomadas de la primera fila del grupo ya que son iguales por campo)
                c11_max = int(df_c['capacidad_f11'].iloc[0])
                c7_max = int(df_c['capacidad_f7'].iloc[0])
                
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

                    # Es conflicto si exceden capacidad O si la capacidad es 0 (campo nuevo)
                    es_conflicto = False
                    if n_f11 > c11_max: es_conflicto = True
                    if n_f11 >= 1 and n_f7 > 0: es_conflicto = True
                    if n_f11 == 0 and n_f7 > c7_max: es_conflicto = True
                    
                    if es_conflicto and len(activos) > 0:
                        conflictos.append({
                            "campo": campo,
                            "c11": c11_max,
                            "c7": c7_max,
                            "hora": tiempo.strftime('%H:%M'),
                            "activos": list(activos)
                        })

            # 5. Renderizado de Tarjetas
            st.subheader("Análisis de Solapamientos y Capacidades")
            if conflictos:
                vistos = set()
                for c in conflictos:
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if (c['campo'], ids) not in vistos:
                        vistos.add((c['campo'], ids))
                        
                        # Creamos la tarjeta
                        with st.container():
                            # Usamos columnas para poner el título y el botón de edición en la misma línea
                            col_tit, col_btn = st.columns([0.85, 0.15])
                            with col_tit:
                                st.markdown(f"### ⚠️ {c['campo']}")
                                st.caption(f"Capacidad actual DB: F11: {c['c11']} | F7: {c['c7']} — Bloqueo en tramo {c['hora']}")
                            with col_btn:
                                if st.button("📝 Editar", key=f"edit_{c['campo']}_{c['hora']}"):
                                    editar_campo_dialog(c['campo'], c['c11'], c['c7'])
                            
                            # Listado de partidos implicados
                            for p in c['activos']:
                                tipo_p = str(p.get('Tipo')).upper()
                                badge_class = "badge-f11" if "11" in tipo_p else "badge-f7"
                                st.markdown(f"""
                                    <div class='match-info'>
                                        <span class='code-badge'>{p.get('Código Partido', 'S/C')}</span> 
                                        <b>{p['Hora']}</b>: {p['Equipo Casa']} vs {p['Equipo Visitante']} 
                                        <span class='{badge_class}'>{tipo_p}</span>
                                    </div>
                                """, unsafe_allow_html=True)
                            st.divider()
            else:
                st.success("✅ No se han detectado conflictos con las capacidades actuales.")

        except Exception as e:
            st.error(f"Error procesando validación: {e}")

# --- PÁGINA DE GESTIÓN (Sigue existiendo para limpieza general) ---
def pagina_gestion():
    st.title("🏟️ Maestro de Instalaciones")
    df_db = obtener_datos_campos()
    df_editado = st.data_editor(df_db[['nombre', 'capacidad_f11', 'capacidad_f7']], num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Guardar Cambios"):
        for _, f in df_editado.iterrows():
            supabase.table("campos").upsert({"nombre": f['nombre'], "capacidad_f11": f['capacidad_f11'], "capacidad_f7": f['capacidad_f7']}, on_conflict="nombre").execute()
        st.success("DB Actualizada")

# --- NAVEGACIÓN ---
pg = st.navigation([
    st.Page(pagina_validacion, title="Validador", icon="🔍"),
    st.Page(pagina_gestion, title="Maestro de Campos", icon="🏟️"),
])
pg.run()
