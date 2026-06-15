import dash
from dash import html

# Inisialisasi App
app = dash.Dash(__name__)

# WAJIB: Variabel server untuk Gunicorn/Hugging Face
server = app.server 

# Layout super sederhana
app.layout = html.Div([
    html.H1("✅ Hugging Face Spaces Berhasil!", style={'color': 'white', 'fontSize': '3rem'}),
    html.P("Jika ini muncul, berarti Space Anda sudah berjalan dengan benar.", style={'color': 'gray', 'fontSize': '1.2rem'})
], style={
    'backgroundColor': '#0f172a', 
    'padding': '100px', 
    'textAlign': 'center', 
    'minHeight': '100vh',
    'fontFamily': 'sans-serif'
})

if __name__ == '__main__':
    app.run_server()
