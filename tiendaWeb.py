import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime
import json

# Configuración de Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_credentials():
    """Obtiene las credenciales desde las variables de entorno o archivo local"""
    try:
        # Primero intenta obtener las credenciales desde las variables de entorno
        if 'GOOGLE_CREDENTIALS' in st.secrets:
            credentials_dict = st.secrets["GOOGLE_CREDENTIALS"]
            creds = service_account.Credentials.from_service_account_info(
                credentials_dict, scopes=SCOPES)
        else:
            # Si no hay variables de entorno, usa el archivo local
            creds = service_account.Credentials.from_service_account_file(
                'credenciales.json', scopes=SCOPES)
        return creds
    except Exception as e:
        st.error(f"Error al obtener credenciales: {str(e)}")
        return None

def conectar_sheet():
    creds = get_credentials()
    if creds:
        service = build('sheets', 'v4', credentials=creds)
        return service
    return None

def obtener_datos_inventario(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Inventario'!A1:F6"
    ).execute()
    valores = result.get('values', [])
    df = pd.DataFrame(valores[1:], columns=valores[0])
    # Convertir columnas numéricas
    df['Cantidad'] = pd.to_numeric(df['Cantidad'])
    df['Precio Compra'] = pd.to_numeric(df['Precio Compra'])
    df['Precio Venta'] = pd.to_numeric(df['Precio Venta'])
    return df

def obtener_datos_ventas(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Ventas'!A:G"
    ).execute()
    valores = result.get('values', [])
    if len(valores) > 1:
        df = pd.DataFrame(valores[1:], columns=valores[0])
        # Asegurarse de que todas las columnas necesarias existen
        columnas_requeridas = ['Fecha', 'Producto', 'Cantidad', 'Precio Unitario', 'Total Venta', 'Beneficio', 'Notas']
        for col in columnas_requeridas:
            if col not in df.columns:
                df[col] = None
        
        # Convertir columnas numéricas, manejando posibles errores
        for col in ['Cantidad', 'Precio Unitario', 'Total Venta', 'Beneficio']:
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except Exception:
                df[col] = 0
        
        # Convertir fechas
        try:
            df['Fecha'] = pd.to_datetime(df['Fecha'], format='%d/%m/%Y', errors='coerce')
        except Exception:
            df['Fecha'] = pd.NaT
    else:
        df = pd.DataFrame(columns=['Fecha', 'Producto', 'Cantidad', 'Precio Unitario', 'Total Venta', 'Beneficio', 'Notas'])
    return df

def obtener_resumen(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Resumen'!A1:B8"
    ).execute()
    return result.get('values', [])

def crear_grafico_inventario(df_inventario):
    fig = go.Figure(data=[
        go.Bar(name='Cantidad', x=df_inventario['Producto'], y=df_inventario['Cantidad']),
    ])
    fig.update_layout(title='Stock Actual por Producto', xaxis_title='Producto', yaxis_title='Cantidad')
    return fig

def crear_grafico_precios(df_inventario):
    fig = go.Figure(data=[
        go.Bar(name='Precio Compra', x=df_inventario['Producto'], y=df_inventario['Precio Compra']),
        go.Bar(name='Precio Venta', x=df_inventario['Producto'], y=df_inventario['Precio Venta'])
    ])
    fig.update_layout(
        title='Comparativa de Precios por Producto',
        xaxis_title='Producto',
        yaxis_title='Precio (€)',
        barmode='group'
    )
    return fig

def crear_grafico_ventas_tiempo(df_ventas):
    if not df_ventas.empty and 'Fecha' in df_ventas.columns and 'Total Venta' in df_ventas.columns:
        # Asegurarse de que tenemos datos válidos
        df_valid = df_ventas.dropna(subset=['Fecha', 'Total Venta'])
        if not df_valid.empty:
            ventas_por_dia = df_valid.groupby('Fecha')['Total Venta'].sum().reset_index()
            fig = px.line(ventas_por_dia, x='Fecha', y='Total Venta',
                         title='Ventas Totales por Día',
                         labels={'Total Venta': 'Ventas (€)', 'Fecha': 'Fecha'})
            return fig
    return None

def crear_grafico_productos_vendidos(df_ventas):
    if not df_ventas.empty and 'Producto' in df_ventas.columns and 'Cantidad' in df_ventas.columns:
        # Asegurarse de que tenemos datos válidos
        df_valid = df_ventas.dropna(subset=['Producto', 'Cantidad'])
        if not df_valid.empty:
            ventas_por_producto = df_valid.groupby('Producto')['Cantidad'].sum().reset_index()
            fig = px.pie(ventas_por_producto, values='Cantidad', names='Producto',
                        title='Distribución de Productos Vendidos')
            return fig
    return None

def registrar_venta(service, producto, cantidad, precio_unitario, notas=""):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Ventas'!A:A"
    ).execute()
    
    ultima_fila = len(result.get('values', [])) + 1
    fecha = datetime.now().strftime("%d/%m/%Y")
    total_venta = float(cantidad) * float(precio_unitario)
    
    inventario = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Inventario'!A2:C6"
    ).execute().get('values', [])
    
    precio_compra = None
    for item in inventario:
        if item[0] == producto:
            precio_compra = float(item[2])
            break
    
    if precio_compra is None:
        raise ValueError(f"Producto '{producto}' no encontrado en el inventario")
    
    beneficio = total_venta - (precio_compra * float(cantidad))
    
    # Asegurarse de que todos los valores numéricos sean strings para la inserción
    venta = [[
        fecha,
        producto,
        str(cantidad),
        str(precio_unitario),
        str(total_venta),
        str(beneficio),
        notas
    ]]
    
    range_name = f"'Ventas'!A{ultima_fila}:G{ultima_fila}"
    body = {'values': venta}
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
        valueInputOption='RAW',
        body=body
    ).execute()
    
    for idx, item in enumerate(inventario, 2):
        if item[0] == producto:
            nueva_cantidad = float(item[1]) - float(cantidad)
            range_name = f"'Inventario'!B{idx}"
            body = {'values': [[str(nueva_cantidad)]]}
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            break

def main():
    st.set_page_config(page_title="Sistema de Gestión de Inventario", layout="wide")
    
    # Obtener SPREADSHEET_ID de forma segura
    try:
        SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
    except Exception:
        SPREADSHEET_ID = '1fD8qCjpv370GIiog8oJP9NHldBOFNZlMWlCqgftA6fs'  # ID por defecto
        
    
    try:
        service = conectar_sheet()
        if not service:
            st.error("No se pudo establecer conexión con Google Sheets")
            return
        
        # Usar tabs en lugar de sidebar
        tab1, tab2 = st.tabs(["📊 Dashboard", "💰 Nueva Venta"])
        
        with tab1:
            st.title("Panel de Control de Inventario")
            
            # Métricas principales
            col1, col2, col3 = st.columns(3)
            resumen = obtener_resumen(service)
            
            with col1:
                st.metric("Inversión Total", resumen[1][1] if len(resumen) > 1 else "0")
            with col2:
                st.metric("Beneficio Potencial", resumen[2][1] if len(resumen) > 2 else "0")
            with col3:
                st.metric("ROI Potencial", f"{resumen[3][1]}%" if len(resumen) > 3 else "0%")
            
            # Gráficos
            df_inventario = obtener_datos_inventario(service)
            df_ventas = obtener_datos_ventas(service)
            
            # Primera fila de gráficos
            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(crear_grafico_inventario(df_inventario), use_container_width=True)
            with col2:
                st.plotly_chart(crear_grafico_precios(df_inventario), use_container_width=True)
            
            # Segunda fila de gráficos
            if not df_ventas.empty:
                col1, col2 = st.columns(2)
                with col1:
                    grafico_ventas = crear_grafico_ventas_tiempo(df_ventas)
                    if grafico_ventas:
                        st.plotly_chart(grafico_ventas, use_container_width=True)
                with col2:
                    grafico_productos = crear_grafico_productos_vendidos(df_ventas)
                    if grafico_productos:
                        st.plotly_chart(grafico_productos, use_container_width=True)
            
            # Tablas de datos
            st.subheader("Inventario Actual")
            st.dataframe(df_inventario, use_container_width=True)
            
            st.subheader("Registro de Ventas")
            st.dataframe(df_ventas, use_container_width=True)
            
        with tab2:
            st.title("Registrar Nueva Venta")
            
            df_inventario = obtener_datos_inventario(service)
            productos_disponibles = df_inventario['Producto'].tolist()
            
            with st.form("formulario_venta"):
                producto = st.selectbox("Seleccionar Producto", productos_disponibles)
                cantidad = st.number_input("Cantidad", min_value=1, max_value=100, value=1)
                
                # Precio por defecto 2.5€ pero permitiendo modificación
                precio_venta = st.number_input(
                    "Precio de venta (€)", 
                    min_value=0.0, 
                    value=2.5, 
                    step=0.1,
                    format="%.2f"
                )
                
                notas = st.text_area("Notas (opcional)", value="Venta")
                
                submitted = st.form_submit_button("Registrar Venta")
                
                if submitted:
                    try:
                        stock_actual = float(df_inventario[df_inventario['Producto'] == producto]['Cantidad'].iloc[0])
                        if cantidad > stock_actual:
                            st.error(f"Error: Stock insuficiente. Solo hay {stock_actual} unidades disponibles.")
                        else:
                            registrar_venta(service, producto, cantidad, precio_venta, notas)
                            st.success("Venta registrada exitosamente")
                            st.balloons()
                            # Recargar la página para actualizar los datos
                            st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Error al registrar la venta: {str(e)}")

    except Exception as e:
        st.error(f"Error de conexión: {str(e)}")

if __name__ == '__main__':
    main()