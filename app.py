import streamlit as st
import google.generativeai as genai
import PyPDF2

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="Datasheet Extractor", page_icon="📄")
st.title("📄 Datasheet AI Extractor")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# --- 2. SETTING API KEY ---
# Ia akan ambil API Key dari Streamlit Secrets (kita akan setup di Langkah 5)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash-latest') # Model yang pantas dan sesuai untuk teks
except KeyError:
    st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
    st.stop()

# --- 3 & 4. INPUT MPN, PROMPT & UPLOAD ---
target_mpn = st.text_input("Enter specific MPN (Optional but recommended for catalogs):")
uploaded_file = st.file_uploader("Upload Datasheet PDF here", type=["pdf"])

if uploaded_file is not None:
    if st.button("Extract Data", type="primary"):
        with st.spinner("Reading PDF and extracting data... Please wait."):
            try:
                # Baca fail PDF
                reader = PyPDF2.PdfReader(uploaded_file)
                pdf_text = ""
                for page in reader.pages:
                    if page.extract_text():
                        pdf_text += page.extract_text() + "\n"
                
                # Setup arahan MPN dinamik
                mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
                
                # Gabungkan prompt dengan teks PDF
                full_prompt = f"""
                Act as an expert electronics engineer. {mpn_instruction}
                Review the provided datasheet text and accurately extract the following information. 
                If a specification varies by part number, ensure you only extract the value corresponding to the requested MPN.

                --- Temperature ---
                1. Operating Temperature (Max) in °C
                2. Operating Temperature (Min) in °C
                3. Storage Temperature (Max) in °C
                4. Storage Temperature (Min) in °C

                --- Physical & Dimensions ---
                5. Length (mm)
                6. Width (mm)
                7. Height (Max) 
                8. Height (mm)
                9. Package Type
                10. Package Type (EIA)
                11. Pitch (Footprint) (mm)
                12. Number of Pins

                --- Electrical Specifications ---
                13. Resistance (Ohm)
                14. Tolerance (%)
                15. Voltage (V)
                16. Function (Choose from: Thin Film / Thick Film / Metal Foil / Wire-Wound / Carbon Film)
                17. Power Consumption (W)
                18. Temperature Coefficient (ppm/K)

                Important Instructions:
                - Provide the final output as a Markdown Table.
                - If a specific piece of information is not clearly stated for the requested MPN, write "N/A". Do not guess or hallucinate data.
                
                Datasheet Text:
                -----------------
                {pdf_text}
                """
                
                # Hantar ke Gemini AI
                response = model.generate_content(full_prompt)
                
                # Papar hasil
                st.success("Extraction Complete!")
                st.markdown(response.text)
                
            except Exception as e:
                st.error(f"Error: {e}")
