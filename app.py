import streamlit as st
import pandas as pd
from datetime import timedelta
import os

st.set_page_config(page_title="Validador de Horarios - Pro", page_icon="⚽", layout="wide")

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
    <style>
    .conflict-card {
        background-color: #fdf2f2;
        border-left: 5px solid #ff4b4b;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 15px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    .card-title {
        color: #ff4b4b;
        font-size: 20px;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .match-info {
        font-size: 15px;
        color: #31333f;
        margin: 8px 0;
        padding-left: 10px;
        border-left: 2px solid #ffcccc;
    }
    .pico-badge {
        background-color: #ff4b4b;
        color: white;
        padding: 2px 8px;
        border-radius: 5px;
        font-size: 14px;
        font-weight: bold;
    }
    .code-badge {
        background-color: #eeeeee;
        color: #555555;
        padding: 1px 6px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 12px;
        margin-right: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# --- PERSISTENCIA ---
def cargar_maestro():
    if os.path.exists('campos.csv'):
        try:
            df = pd.read_csv('campos.csv', sep=';', encoding='latin-1')
            df['Campo'] = df['Campo'].str.strip()
            return df
        except:
            return pd.DataFrame(columns=['Campo', 'Capacidad'])
    return pd.DataFrame(columns=['Campo', 'Capacidad'])

def guardar_maestro(df):
    df.to_csv('campos.csv', sep=';', index=False, encoding='latin-1')

st.title("⚽ Panel de Control de Instalaciones")

with st.sidebar:
    st.header("Configuración")
    minutos_duracion = st.number_input("Duración partido (min):", min_value=1, value=105, step=5)
    st.divider()
    st.caption("v2.1 - Identificación por Código de Partido")

archivo_partidos = st.file_uploader("Sube el CSV de Partidos", type=['csv'])

if archivo_partidos:
    try:
        try:
            df_raw = pd.read_csv(archivo_partidos, sep=';', encoding='utf-8')
        except UnicodeDecodeError:
            archivo_partidos.seek(0)
            df_raw = pd.read_csv(archivo_partidos, sep=';', encoding='latin-1')

        # --- ANOMALÍAS ---
        # Detectamos si falta Fecha o Hora
        anomalias = df_raw[df_raw['Fecha'].isna() | df_raw['Hora'].isna() | (df_raw['Fecha'].astype(str).str.strip() == "") | (df_raw['Hora'].astype(str).str.strip() == "")].copy()
        
        if not anomalias.empty:
            with st.expander("⚠️ Ver Anomalías (Partidos sin fecha/hora)", expanded=True):
                # Mostramos columnas clave incluyendo el Código Partido
                cols_mostrar = ['Código Partido', 'Fecha', 'Hora', 'Equipo Casa', 'Equipo Visitante', 'Campo']
                cols_existentes = [c for c in cols_mostrar if c in anomalias.columns]
                st.dataframe(
                    anomalias[cols_existentes].style.set_properties(**{'background-color': '#ffffcc', 'color': 'black'}), 
                    use_container_width=True, 
                    hide_index=True
                )

        # --- PROCESAMIENTO ---
        df_partidos = df_raw.dropna(subset=['Fecha', 'Hora', 'Campo']).copy()
        df_partidos['Campo'] = df_partidos['Campo'].astype(str).str.strip()
        campos_detectados = sorted(df_partidos['Campo'].unique())

        # Configuración de Capacidades
        df_maestro = cargar_maestro()
        df_interfaz = pd.DataFrame({'Campo': campos_detectados})
        df_interfaz = pd.merge(df_interfaz, df_maestro, on='Campo', how='left')
        df_interfaz['Capacidad'] = df_interfaz['Capacidad'].fillna(1).astype(int)

        with st.expander("⚙️ Configuración de Capacidades de los Campos", expanded=False):
            df_capacidades_final = st.data_editor(df_interfaz, use_container_width=True, hide_index=True, disabled=["Campo"], key="editor_dinamico")
            if st.button("💾 Guardar capacidades"):
                guardar_maestro(df_capacidades_final)
                st.success("Base de datos actualizada.")

        # --- VALIDACIÓN ---
        st.divider()
        dict_capacidades = dict(zip(df_capacidades_final['Campo'], df_capacidades_final['Capacidad']))
        df_validar = df_partidos.copy()
        df_validar['Inicio'] = pd.to_datetime(df_validar['Fecha'].astype(str) + ' ' + df_validar['Hora'].astype(str), dayfirst=True, errors='coerce')
        df_validar = df_validar.dropna(subset=['Inicio'])
        df_validar['Fin'] = df_validar['Inicio'] + timedelta(minutes=minutos_duracion)

        conflictos = []
        for campo in campos_detectados:
            df_este_campo = df_validar[df_validar['Campo'] == campo]
            capacidad_max = int(dict_capacidades.get(campo, 1))
            eventos = []
            for _, p in df_este_campo.iterrows():
                eventos.append((p['Inicio'], 1, p))
                eventos.append((p['Fin'], -1, p))
            
            eventos.sort(key=lambda x: (x[0], x[1]))
            carga_actual = 0
            partidos_activos = []
            
            for tiempo, tipo, p_data in eventos:
                if tipo == 1:
                    carga_actual += 1
                    partidos_activos.append(p_data)
                else:
                    carga_actual -= 1
                    id_p = str(p_data.get('Código Partido', ''))
                    partidos_activos = [p for p in partidos_activos if str(p.get('Código Partido', '')) != id_p]
                
                if carga_actual > capacidad_max:
                    conflictos.append({
                        "Campo": campo,
                        "Capacidad": capacidad_max,
                        "Lista_Partidos": list(partidos_activos),
                        "Pico": carga_actual,
                        "Hora": tiempo.strftime('%H:%M')
                    })

        # --- RESULTADOS ---
        st.subheader("🔍 Estado de la Instalación")
        
        if conflictos:
            vistos = set()
            conflictos_unicos = []
            for c in conflictos:
                ids = sorted([str(p.get('Código Partido', '')) for p in c['Lista_Partidos']])
                key = (c['Campo'], tuple(ids))
                if key not in vistos:
                    vistos.add(key)
                    conflictos_unicos.append(c)

            st.error(f"Se han detectado {len(conflictos_unicos)} colisiones de horario:")
            
            for conf in conflictos_unicos:
                partidos_html = ""
                for p in conf['Lista_Partidos']:
                    cod = p.get('Código Partido', 'N/A')
                    partidos_html += f"""
                    <div class='match-info'>
                        <span class='code-badge'>{cod}</span>
                        🕒 <b>{p['Hora']}</b> - {p['Equipo Casa']} vs {p['Equipo Visitante']}
                    </div>"""
                
                st.markdown(f"""
                    <div class="conflict-card">
                        <div class="card-title">⚠️ {conf['Campo']}</div>
                        <div style="margin-bottom: 10px;">
                            <span class="pico-badge">Exceso: {conf['Pico']} partidos</span>
                            <span style="margin-left:10px; color:#666;">Capacidad: {conf['Capacidad']}</span>
                        </div>
                        <hr style="margin: 10px 0; border: 0; border-top: 1px solid #ffcccc;">
                        {partidos_html}
                        <div style="margin-top: 10px; font-size: 13px; color: #888;">
                            <i>Pico de carga detectado a las {conf['Hora']}</i>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ Todo despejado. No hay solapamientos detectados.")
            st.balloons()

    except Exception as e:
        st.error(f"Error: {e}")