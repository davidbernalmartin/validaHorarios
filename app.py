import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client

# --- CONFIGURACIÓN DE CONEXIÓN SEGURA ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Gestor de Instalaciones ⚽", layout="wide")

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    .conflict-card { background-color: #fdf2f2; border-left: 5px solid #ff4b4b; padding: 20px; border-radius: 10px; margin-bottom: 15px; }
    .match-info { font-size: 14px; margin: 8px 0; padding: 8px; background-color: white; border-radius: 5px; border-left: 3px solid #ffcccc; }
    .badge-f11 { background: #1f77b4; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .badge-f7 { background: #2ca02c; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIONES DE BASE DE DATOS ---

def obtener_datos_campos():
    try:
        res = supabase.table("campos").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7'])

def upsert_campos(df_editado):
    for _, fila in df_editado.iterrows():
        data = {
            "nombre": str(fila['nombre']).strip(),
            "capacidad_f11": int(fila['capacidad_f11']),
            "capacidad_f7": int(fila['capacidad_f7'])
        }
        supabase.table("campos").upsert(data, on_conflict="nombre").execute()

# --- PÁGINA 1: GESTIÓN DE CAMPOS ---

def pagina_gestion():
    st.title("🏟️ Gestión de Instalaciones")
    st.write("Sincroniza los campos del CSV con la base de datos de Supabase.")
    
    # 1. Cargamos lo que ya tenemos en Supabase
    df_db = obtener_datos_campos()
    
    # 2. Subida de archivo para ESCANEAR nuevos campos
    with st.expander("📥 Importar campos nuevos desde CSV", expanded=True):
        archivo_scan = st.file_uploader("Sube el CSV para buscar campos nuevos", type=['csv'], key="scanner")
        
        if archivo_scan:
            try:
                # Lectura rápida del CSV
                df_temp = pd.read_csv(archivo_scan, sep=';', encoding='latin-1')
                df_temp.columns = df_temp.columns.str.strip()
                campos_en_csv = set(df_temp['Campo'].dropna().astype(str).str.strip().unique())
                
                # Campos que ya existen en DB
                campos_en_db = set(df_db['nombre'].unique()) if not df_db.empty else set()
                
                # Detectamos los que faltan
                nuevos_campos = campos_en_csv - campos_en_db
                
                if nuevos_campos:
                    st.warning(f"Se han detectado {len(nuevos_campos)} campos nuevos.")
                    if st.button("➕ Añadir nuevos a la lista con F11:0 y F7:1"):
                        # Creamos los nuevos registros
                        registros_nuevos = []
                        for nombre in nuevos_campos:
                            registros_nuevos.append({
                                "nombre": nombre,
                                "capacidad_f11": 0,
                                "capacidad_f7": 1
                            })
                        
                        # Los subimos a Supabase
                        with st.spinner("Registrando nuevos campos..."):
                            for reg in registros_nuevos:
                                supabase.table("campos").insert(reg).execute()
                            st.success("Campos añadidos. Refrescando...")
                            st.cache_data.clear()
                            st.rerun()
                else:
                    st.success("✅ Todos los campos de este CSV ya están registrados en la base de datos.")
            except Exception as e:
                st.error(f"Error al escanear: {e}")

    # 3. Listado y Edición Manual
    st.subheader("📋 Listado Maestro de Campos")
    st.info("Aquí puedes ajustar las capacidades finales de cada campo.")
    
    # Refrescamos df_db por si acabamos de insertar
    df_db = obtener_datos_campos()
    
    if not df_db.empty:
        df_editado = st.data_editor(
            df_db[['nombre', 'capacidad_f11', 'capacidad_f7']],
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="editor_maestro"
        )
        
        if st.button("💾 Guardar Cambios Manuales"):
            with st.spinner("Sincronizando..."):
                upsert_campos(df_editado)
                st.success("¡Base de datos actualizada!")
                st.cache_data.clear()
    else:
        st.write("No hay campos registrados todavía.")

# --- PÁGINA 2: VALIDACIÓN ---

# --- DIÁLOGO PARA AÑADIR CAMPO ---
@st.dialog("Configurar Nuevo Campo")
def modal_nuevo_campo(nombre_campo):
    st.write(f"Estás configurando el campo: **{nombre_campo}**")
    c11 = st.number_input("Capacidad Fútbol 11", min_value=0, value=0)
    c7 = st.number_input("Capacidad Fútbol 7", min_value=0, value=1)
    
    if st.button("Guardar en Base de Datos"):
        data = {
            "nombre": nombre_campo,
            "capacidad_f11": c11,
            "capacidad_f7": c7
        }
        supabase.table("campos").upsert(data, on_conflict="nombre").execute()
        st.success(f"Campo '{nombre_campo}' guardado.")
        st.cache_data.clear()
        st.rerun()

# --- PÁGINA 2: VALIDACIÓN ---
def pagina_validacion():
    st.title("🔍 Validación de Horarios")
    
    with st.sidebar:
        st.header("Ajustes")
        duracion = st.number_input("Duración partido (min):", value=105)
    
    archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])
    
    if archivo:
        try:
            # Carga de datos
            try:
                df_raw = pd.read_csv(archivo, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                archivo.seek(0)
                df_raw = pd.read_csv(archivo, sep=';', encoding='latin-1')
            
            df_raw.columns = df_raw.columns.str.strip()
            df_raw['Campo'] = df_raw['Campo'].astype(str).str.strip()
            
            # 1. Obtener campos de Supabase
            df_db = obtener_datos_campos()
            campos_conocidos = set(df_db['nombre'].unique()) if not df_db.empty else set()
            campos_en_csv = set(df_raw['Campo'].unique())
            
            # 2. Detectar campos desconocidos
            desconocidos = campos_en_csv - campos_conocidos
            
            if desconocidos:
                st.warning(f"⚠️ Se han detectado {len(desconocidos)} campos que no están en la Base de Datos.")
                cols = st.columns(len(desconocidos) if len(desconocidos) < 4 else 4)
                for i, campo in enumerate(desconocidos):
                    with cols[i % 4]:
                        if st.button(f"Configurar {campo}", key=f"btn_{campo}"):
                            modal_nuevo_campo(campo)
                st.divider()

            # 3. Proceder con la validación solo de los campos conocidos
            # Filtramos el CSV para validar solo lo que tenemos en DB
            df_validar_raw = df_raw[df_raw['Campo'].isin(campos_conocidos)].copy()
            
            if df_validar_raw.empty:
                st.info("Configura los campos desconocidos para ver los solapamientos.")
                return

            # Unimos con capacidades
            df_validar = pd.merge(df_validar_raw, df_db, left_on='Campo', right_on='nombre', how='left')
            df_validar['Inicio'] = pd.to_datetime(df_validar['Fecha'] + ' ' + df_validar['Hora'], dayfirst=True, errors='coerce')
            df_validar = df_validar.dropna(subset=['Inicio'])
            df_validar['Fin'] = df_validar['Inicio'] + timedelta(minutes=duracion)

            # --- LÓGICA DE VALIDACIÓN ---
            conflictos = []
            for campo in df_validar['Campo'].unique():
                df_campo = df_validar[df_validar['Campo'] == campo]
                row_db = df_db[df_db['nombre'] == campo].iloc[0]
                cap_f11_max = int(row_db['capacidad_f11'])
                cap_f7_max = int(row_db['capacidad_f7'])

                eventos = []
                for _, p in df_campo.iterrows():
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

                    conflicto = False
                    if n_f11 > cap_f11_max: conflicto = True
                    if n_f11 >= 1 and n_f7 > 0: conflicto = True
                    if n_f11 == 0 and n_f7 > cap_f7_max: conflicto = True

                    if conflicto:
                        conflictos.append({"campo": campo, "hora": tiempo.strftime('%H:%M'), "activos": list(activos)})

            # 4. Mostrar Resultados
            st.subheader("🔍 Resultados del Análisis")
            if conflictos:
                vistos = set()
                for c in conflictos:
                    ids = tuple(sorted([str(p.get('Código Partido')) for p in c['activos']]))
                    if ids not in vistos:
                        vistos.add(ids)
                        partidos_html = "".join([f"<div class='match-info'><span class='code-badge'>{p.get('Código Partido', 'S/C')}</span> <b>{p['Hora']}</b> - {p['Equipo Casa']} vs {p['Equipo Visitante']} <span class='badge-{str(p['Tipo']).lower()}'>{p['Tipo']}</span></div>" for p in c['activos']])
                        st.markdown(f"""
                            <div class="conflict-card">
                                <div class="card-title">⚠️ {c['campo']} (Tramo {c['hora']})</div>
                                {partidos_html}
                            </div>
                        """, unsafe_allow_html=True)
            else:
                st.success("✅ Validación completada: Sin conflictos en los campos conocidos.")

        except Exception as e:
            st.error(f"Error: {e}")

# --- NAVEGACIÓN ---

pg = st.navigation([
    st.Page(pagina_validacion, title="Validador de Partidos", icon="🔍"),
    st.Page(pagina_gestion, title="Gestión de Campos", icon="🏟️"),
])
pg.run()
