import streamlit as st
import pandas as pd
from datetime import timedelta
from supabase import create_client, Client

# --- CONFIGURACIÓN DE CONEXIÓN ---
# Asegúrate de que estos valores son correctos
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Gestor de Sedes Pro", page_icon="⚽", layout="wide")

# --- FUNCIONES DE BASE DE DATOS ---

def obtener_datos_campos():
    try:
        res = supabase.table("campos").select("*").execute()
        df = pd.DataFrame(res.data)
        if df.empty:
            # Si la tabla existe pero está vacía, devolvemos estructura base
            return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7'])
        return df
    except Exception as e:
        st.warning(f"Nota: No se pudieron cargar datos previos (posible tabla vacía).")
        return pd.DataFrame(columns=['nombre', 'capacidad_f11', 'capacidad_f7'])

def upsert_campos(df_editado):
    for _, fila in df_editado.iterrows():
        # Limpieza de datos antes de enviar a Supabase
        data = {
            "nombre": str(fila['nombre']).strip(),
            "capacidad_f11": int(fila['capacidad_f11']),
            "capacidad_f7": int(fila['capacidad_f7'])
        }
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

        # Limpiar nombres de columnas del CSV (por si hay espacios)
        df_partidos.columns = df_partidos.columns.str.strip()
        df_partidos['Campo'] = df_partidos['Campo'].astype(str).str.strip()
        campos_csv = sorted(df_partidos['Campo'].unique())

        # 2. Sincronización con Supabase
        st.subheader("🏟️ Configuración de Campos Detectados")
        
        df_db = obtener_datos_campos()
        
        # Crear la tabla de la interfaz asegurando que existen las columnas
        df_interfaz = pd.DataFrame({'nombre': campos_csv})
        
        if not df_db.empty:
            # Unimos solo si hay datos, si no, Pandas creará las columnas con NaN
            df_interfaz = pd.merge(df_interfaz, df_db[['nombre', 'capacidad_f11', 'capacidad_f7']], on='nombre', how='left')
        else:
            df_interfaz['capacidad_f11'] = 1
            df_interfaz['capacidad_f7'] = 2

        # Asegurar que las columnas existen y no tienen fallos de tipo
        for col in ['capacidad_f11', 'capacidad_f7']:
            if col not in df_interfaz.columns:
                df_interfaz[col] = 1 if col == 'capacidad_f11' else 2
            df_interfaz[col] = df_interfaz[col].fillna(1 if col == 'capacidad_f11' else 2).astype(int)

        with st.expander("⚙️ Editar capacidades F11 / F7", expanded=False):
            df_final_campos = st.data_editor(
                df_interfaz[['nombre', 'capacidad_f11', 'capacidad_f7']],
                use_container_width=True,
                hide_index=True,
                disabled=["nombre"]
            )
            
            if st.button("💾 Guardar cambios en Supabase"):
                with st.spinner("Guardando en la nube..."):
                    upsert_campos(df_final_campos)
                    st.success("¡Base de datos actualizada!")
                    st.rerun()

        st.info("Configuración cargada correctamente. Listo para procesar la lógica F7/F11.")

    except Exception as e:
        st.error(f"Error detallado: {e}")
