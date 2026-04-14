import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Gestor de Sedes Supabase", page_icon="⚽", layout="wide")

# --- FUNCIONES DE BASE DE DATOS ---

def obtener_datos_campos():
    """Trae todos los campos guardados en Supabase"""
    res = supabase.table("campos").select("*").execute()
    return pd.DataFrame(res.data)

def upsert_campos(df_editado):
    """Guarda o actualiza los campos en la nube"""
    for _, fila in df_editado.iterrows():
        data = {
            "nombre": fila['nombre'],
            "capacidad_f11": int(fila['capacidad_f11']),
            "capacidad_f7": int(fila['capacidad_f7'])
        }
        # Upsert: Si el nombre existe actualiza, si no inserta
        supabase.table("campos").upsert(data, on_conflict="nombre").execute()

# --- INTERFAZ ---

st.title("⚽ Validación de Instalaciones (F7/F11)")

archivo = st.file_uploader("Sube el CSV de Partidos", type=['csv'])

if archivo:
    try:
        # 1. Carga de Partidos
        try:
            df_partidos = pd.read_csv(archivo, sep=';', encoding='utf-8')
        except UnicodeDecodeError:
            archivo.seek(0)
            df_partidos = pd.read_csv(archivo, sep=';', encoding='latin-1')

        df_partidos['Campo'] = df_partidos['Campo'].str.strip()
        campos_csv = sorted(df_partidos['Campo'].unique())

        # 2. Sincronización con Supabase
        st.subheader("🏟️ Configuración de Campos Detectados")
        
        df_db = obtener_datos_campos()
        
        # Mezclamos lo que hay en el CSV con lo que hay en la DB
        df_interfaz = pd.DataFrame({'nombre': campos_csv})
        if not df_db.empty:
            df_interfaz = pd.merge(df_interfaz, df_db[['nombre', 'capacidad_f11', 'capacidad_f7']], on='nombre', how='left')
        
        # Valores por defecto para campos nuevos
        df_interfaz['capacidad_f11'] = df_interfaz['capacidad_f11'].fillna(1).astype(int)
        df_interfaz['capacidad_f7'] = df_interfaz['capacidad_f7'].fillna(2).astype(int)

        with st.expander("⚙️ Editar capacidades F11 / F7", expanded=False):
            df_final_campos = st.data_editor(
                df_interfaz,
                use_container_width=True,
                hide_index=True,
                disabled=["nombre"] # El nombre no se toca para no romper la relación
            )
            
            if st.button("💾 Guardar cambios en Supabase"):
                with st.spinner("Sincronizando con la nube..."):
                    upsert_campos(df_final_campos)
                    st.success("¡Base de datos actualizada!")
                    st.rerun()

        # 3. Próximo Paso: La Validación
        st.info("💡 Los campos ya están conectados con Supabase. Ahora falta que definamos la lógica: ¿Cómo quieres que el sistema reste capacidad cuando coinciden tipos distintos?")

    except Exception as e:
        st.error(f"Error de conexión o lectura: {e}")
