import streamlit as st
import os
os.system("playwright install chromium")
os.system("playwright install-deps")
import asyncio
import nest_asyncio
import re
import pandas as pd
from playwright.async_api import async_playwright

nest_asyncio.apply()

# --- 1. FUNCIONES DE LIMPIEZA ---
def limpiar_reviews_a_numero(rev_str):
    if not rev_str or rev_str == "N/A": return 0
    s = str(rev_str).lower().replace("+", "").replace(",", "").strip()
    try:
        if "k" in s:
            s = s.replace("k", "")
            return int(float(s) * 1000)
        return int(float(s))
    except ValueError:
        return 0

def limpiar_tiempo_a_numero(tiempo_str):
    if not tiempo_str or tiempo_str == "N/A": return 0
    numeros = re.findall(r'\d+', str(tiempo_str))
    if len(numeros) == 1: return int(numeros[0])
    elif len(numeros) >= 2: return int((int(numeros[0]) + int(numeros[1])) / 2)
    return 0

# --- 2. MOTOR DEL SCRAPER ---
async def ejecutar_auditoria(zona, url, scrolls):
    if not url: return pd.DataFrame()

    todos_los_datos = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-MX"
        )
        page = await context.new_page()

        try:
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await asyncio.sleep(6)

            for i in range(scrolls):
                await page.keyboard.press("PageDown")
                await asyncio.sleep(1.2)
                await page.evaluate("window.scrollBy(0, 1400)")
                await asyncio.sleep(1.2)

            bloques = await page.query_selector_all("li, div[data-testid='store-card'], div[role='article']")
            for b in bloques:
                texto = await b.inner_text()
                if not texto: continue
                lineas_txt = [l.strip() for l in texto.split("\n") if l.strip()]
                if not any("min" in l.lower() for l in lineas_txt) or len(lineas_txt) < 3: continue

                nombre = lineas_txt[0]
                if any(k in nombre.lower() for k in ["oferta", "ahorra", "patrocinado", "gasta"]) and len(lineas_txt) > 1:
                    nombre = lineas_txt[1]

                rating_raw, reviews_raw, tiempo_raw = "N/A", "N/A", "N/A"
                for l in lineas_txt:
                    if "min" in l.lower() and tiempo_raw == "N/A": tiempo_raw = l
                    match_completo = re.search(r'([1-5]\.[0-9])\s*(?:•|\s*)\s*\(([^\)]+)\)', l)
                    if match_completo:
                        rating_raw = match_completo.group(1)
                        reviews_raw = match_completo.group(2).strip()
                    else:
                        match_solo_rating = re.search(r'\b([1-5]\.[0-9])\b', l)
                        if match_solo_rating and rating_raw == "N/A": rating_raw = match_solo_rating.group(1)
                        match_solo_reviews = re.search(r'\(([0-9kK\+\,\.\s]+)\)', l)
                        if match_solo_reviews and reviews_raw == "N/A": reviews_raw = match_solo_reviews.group(1).strip()

                try: rating_num = float(rating_raw) if rating_raw != "N/A" else 0.0
                except ValueError: rating_num = 0.0

                todos_los_datos.append({
                    "Zona": zona,
                    "Restaurante": nombre,
                    "Rating": rating_num,
                    "Reviews": limpiar_reviews_a_numero(reviews_raw),
                    "Tiempo_Entrega_Min": limpiar_tiempo_a_numero(tiempo_raw)
                })
        except Exception as e:
            st.error(f"Error escaneando: {e}")
        finally:
            await context.close()
        await browser.close()

    df = pd.DataFrame(todos_los_datos).drop_duplicates(subset=["Zona", "Restaurante"])
    if not df.empty:
        df = df[df["Restaurante"] != "No detectado"]
        df = df.sort_values(by=["Zona", "Reviews"], ascending=[True, False]).reset_index(drop=True)
    return df

# --- 3. DISEÑO DE LA PÁGINA WEB ---
st.set_page_config(page_title="Adquisición de Restaurantes", page_icon="🍔", layout="centered")

st.title("🍔 Herramienta de Adquisición")
st.markdown("Copia y pega la URL de la zona desde Uber Eats para extraer automáticamente la lista de restaurantes.")

with st.container():
    zona_nombre = st.text_input("Nombre de la Zona (Ej. Prueba JV)", "")
    zona_url = st.text_input("Enlace (URL) de la plataforma", "")

    profundidad = st.selectbox(
        "¿Cuántos restaurantes quieres extraer?",
        ["Rápida (~40-80 tiendas)", "Normal (~80-150 tiendas)", "Profunda (~200-350 tiendas)"]
    )

    mapa_scrolls = {"Rápida (~40-80 tiendas)": 8, "Normal (~80-150 tiendas)": 15, "Profunda (~200-350 tiendas)": 28}
    scrolls_seleccionados = mapa_scrolls[profundidad]

if st.button("🚀 Iniciar Extracción", type="primary", use_container_width=True):
    if not zona_url or "http" not in zona_url:
        st.warning("⚠️ Por favor ingresa una URL válida.")
    elif not zona_nombre:
        st.warning("⚠️ Por favor ponle un nombre a la zona.")
    else:
        with st.spinner(f'Navegando en {zona_nombre}... Esto puede tomar 1 o 2 minutos.'):
            df_resultado = asyncio.run(ejecutar_auditoria(zona_nombre, zona_url, scrolls_seleccionados))

            if not df_resultado.empty:
                st.success(f"¡Éxito! Se extrajeron {len(df_resultado)} restaurantes en {zona_nombre}.")

                # Mostrar la tabla en la página
                st.dataframe(df_resultado, use_container_width=True)

                # Botón para descargar
                csv = df_resultado.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="📥 Descargar Base de Datos (CSV)",
                    data=csv,
                    file_name=f"restaurantes_{zona_nombre.replace(' ', '_')}.csv",
                    mime="text/csv"
                )
            else:
                st.error("No se pudo extraer la información. Revisa el enlace.")
