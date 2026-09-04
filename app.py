import streamlit as st
import google.generativeai as genai
import PyPDF2
import json

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="R* Datasheet Extractor", page_icon="📄")
st.title("📄 R* Datasheet Extractor")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# --- 2. SETTING API KEY & PENGGUNAAN MODEL TERKINI ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # Menggunakan model gemini-3.6-flash seperti yang diminta oleh sistem Google
    model = genai.GenerativeModel('gemini-3.6-flash')
    
except KeyError:
    st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
    st.stop()
except Exception as e:
    st.error(f"Ralat API: {e}")
    st.stop()
    
# --- 3 & 4. INPUT MPN, PROMPT & UPLOAD ---
target_mpn = st.text_input("Enter specific MPN (Optional but recommended for catalogs):")
uploaded_file = st.file_uploader("Upload Datasheet PDF here", type=["pdf"])

if uploaded_file is not None:
    if st.button("Extract Data", type="primary"):
        with st.spinner("Reading PDF and extracting data... Please wait."):
            try:
                reader = PyPDF2.PdfReader(uploaded_file)
                pdf_text = "".join([page.extract_text() + "\n" for page in reader.pages if page.extract_text()])
                
                mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
                
                full_prompt = f"""
                Act as an expert electronics engineer. {mpn_instruction}
                Review the provided datasheet text and accurately extract the requested information. 
                
                Extract these exact keys:
                "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
                "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)", 
                "Length (mm)", "Width (mm)", "Height (Max)", "Height (mm)", 
                "Package Type", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins", 
                "Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", 
                "Power Consumption (W)", "Temperature Coefficient (ppm/K)"

                Important Instructions:
                - Return strictly a valid JSON object with the keys above.
                - The values must be strings.
                - If data is missing, use the value "N/A".
                - FOR THE "Function" KEY: You MUST select ONLY ONE of the following options based on the datasheet: "Thin Film", "Thick Film", "Metal Foil", "Wire-wound", or "Carbon Film". If none apply, output "N/A". Do not write any other text.
                
                Datasheet Text:
                -----------------
                {pdf_text}
                """
                
                # Paksa output JSON dan konsisten penuh (temperature = 0)
                response = model.generate_content(
                    full_prompt,
                    generation_config={
                        "temperature": 0.0,
                        "response_mime_type": "application/json"
                    }
                )
                
                # Tukar JSON dari AI kepada jadual Streamlit
                extracted_data = json.loads(response.text)
                
                # Susun data untuk paparan cantik dengan lajur Unit berasingan
                specs = []
                values = []
                units = []
                
                for key, val in extracted_data.items():
                    # Pisahkan nama dan unit berdasarkan key yang kita dah tetapkan
                    if "(°C)" in key:
                        specs.append(key.replace(" (°C)", ""))
                        units.append("°C")
                    elif "(mm)" in key:
                        specs.append(key.replace(" (mm)", ""))
                        units.append("mm")
                    elif "(Ohm)" in key:
                        specs.append(key.replace(" (Ohm)", ""))
                        units.append("Ohm")
                    elif "(%)" in key:
                        specs.append(key.replace(" (%)", ""))
                        units.append("%")
                    elif "(V)" in key:
                        specs.append(key.replace(" (V)", ""))
                        units.append("V")
                    elif "(W)" in key:
                        specs.append(key.replace(" (W)", ""))
                        units.append("W")
                    elif "(ppm/K)" in key:
                        specs.append(key.replace(" (ppm/K)", ""))
                        units.append("ppm/K")
                    else:
                        specs.append(key)
                        units.append("-") # Letak sengkang jika tiada unit
                        
                    values.append(val)
                
                table_data = {
                    "Specification": specs,
                    "Extracted Value": values,
                    "Unit": units
                }
                
                st.success("Extraction Complete!")
                st.table(table_data) 
                
            except Exception as e:
                st.error(f"Error happened!: {e}")
                
                # Susun data untuk paparan cantik
                table_data = {
                    "Specification": list(extracted_data.keys()),
                    "Extracted Value": list(extracted_data.values())
                }
                
                st.success("Extraction Complete!")
                st.table(table_data) # Ini menjamin jadual sentiasa sama
                
            except Exception as e:
                st.error(f"Error happened!: {e}")
