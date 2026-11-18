import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   
import random 
import csv 
import io
import os
import copy
import html
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta
from asi_rules import render_asi, asi_csv_rows
from asi_alternatives import render_alternatives
from dms_lookup import dms_sidebar, render_duplicate_check
from ui_style import (apply_style, render_summary, callout, md_safe,
                      brand, page_title, theme_toggle, card, split, segmented)
from extract_rules import detect_manufacturer, detect_commodity_group, quantity_from
from rules_registry import determine_asi_for_cg
from rules_rt import rt_designation
from categories import CATEGORIES, RESISTOR
from commodities import COMMODITIES, ALL_CATEGORIES, build_prompt_any, detect_commodity
from categories_l import CATEGORIES_L, snap_pick_lists
from rules_l import resolve_manufacturer_l, determine_cg_l, cg_label
from categories_c import snap_pick_lists_c
from rules_c import resolve_manufacturer_c, determine_cg_c, cg_label_c, clean_designation_c
from processability import apply_processability

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="Datasheet Analyzer", page_icon="📄", layout="wide", initial_sidebar_state="auto")
# mod gelap/terang: tema Streamlit sendiri (.streamlit/config.toml) - butang bulan/matahari di top bar
apply_style()

# --- TARIKH KEMASKINI KOD (dari commit GitHub terakhir) ---
GITHUB_REPO = "syafiqfauzi-work/RG-datasheet-extractor"

@st.cache_data(ttl=600)
def get_last_update():
    sgt = timezone(timedelta(hours=8))
    def fmt(iso):
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(sgt).strftime("%d/%m/%Y %H:%M")
    # 1) commit terakhir dari git clone (jika git tersedia)
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cI"], capture_output=True, text=True,
                             timeout=5, cwd=os.path.dirname(os.path.abspath(__file__)))
        if out.returncode == 0 and out.stdout.strip():
            return fmt(out.stdout.strip())
    except Exception:
        pass
    # 2) commit terakhir dari GitHub API (repo private: letak GITHUB_TOKEN dalam Streamlit Secrets)
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "rg-datasheet-analyzer"}
        try:
            headers["Authorization"] = f"Bearer {st.secrets['GITHUB_TOKEN']}"
        except Exception:
            pass
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=1", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return fmt(json.loads(resp.read())[0]["commit"]["committer"]["date"])
    except Exception:
        pass
    # 3) fallback: masa fail diubah
    return datetime.fromtimestamp(os.path.getmtime(__file__), timezone(timedelta(hours=8))).strftime("%d/%m/%Y %H:%M")

# --- COMMODITY: Auto-detect (lalai) atau pilihan manual R* / L* / C* ---
COMMODITY_OPTIONS = {"Auto-detect": None, "R* Resistor": "R*", "L* Inductor": "L*", "C* Capacitor": "C*"}
if "commodity_choice" not in st.session_state:
    st.session_state.commodity_choice = "Auto-detect"

def effective_commodity():
    """Manual choice wins; otherwise the commodity detected for the current job (None before extraction)."""
    manual = COMMODITY_OPTIONS[st.session_state.commodity_choice]
    job_ = st.session_state.get("job")
    return manual or (job_["auto_commodity"] if job_ else None)

# --- TOP BAR: kiri = jenama | kanan = tarikh kemaskini + butang mod gelap/terang ---
with st.container(key="ds_topbar", horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
    brand("Component Engineering")
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                      gap="small", width="content"):
        st.markdown(f'<span class="update-pill">🕒 Last update: {get_last_update()} SGT</span>',
                    unsafe_allow_html=True, width="content")
        theme_toggle()
page_title("Datasheet Analyzer", notice="Upload a datasheet (PDF) and the AI will extract the key specifications.")

# --- PANGGILAN MODEL AI (dengan retry) ---
def call_model(full_prompt, progress_bar):
    max_retries = 3
    retry_delay = 15
    for attempt in range(max_retries):
        try:
            api_keys = st.secrets["GEMINI_API_KEY"].split(",")
            selected_key = random.choice(api_keys).strip()
            genai.configure(api_key=selected_key)
            model = genai.GenerativeModel('gemini-3.5-flash-lite')

            response = model.generate_content(
                full_prompt,
                generation_config={
                    "temperature": 0.0,
                    "response_mime_type": "application/json"
                }
            )
            data = json.loads(response.text, strict=False)
            progress_bar.progress(80, text="AI extraction complete. Parsing data...")
            return data

        except KeyError:
            progress_bar.empty()
            st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
            st.stop()

        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if attempt < max_retries - 1:
                    progress_bar.progress(40, text=f"API limit reached. Auto-retrying in {retry_delay}s... (Trial {attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    progress_bar.empty()
                    st.error("Failed after 3 trials. Rilex & wait for a minute, then try again.")
                    st.stop()
            else:
                progress_bar.empty()
                st.error(f"API Error: {e}")
                st.stop()
    return None

# --- BACA PDF ---
def read_pdfs(uploaded_file, spec_file, progress_bar):
    pdf_text = ""
            
    # --- BACA SPEC SHEET DAHULU (JIKA ADA) ---
    if spec_file is not None:
        spec_reader = PyPDF2.PdfReader(spec_file)
        if spec_reader.is_encrypted:
            try:
                spec_reader.decrypt("")
            except Exception:
                pass
        spec_text = "".join([page.extract_text() for page in spec_reader.pages if page.extract_text()])
        pdf_text += f"\n\n=== CRITICAL PRIORITY: SPECIFIC SPEC SHEET ===\n{spec_text}\n\n=== GENERAL DATASHEET ===\n"
            
    # --- BACA DATASHEET SEPERTI BIASA ---
    if uploaded_file is not None:
        reader = PyPDF2.PdfReader(uploaded_file)
                
        # --- PENAPIS KESELAMATAN (SECURITY BYPASS) ---
        if reader.is_encrypted:
            try:
                reader.decrypt("") # Buka kunci AES dengan kata laluan kosong
            except Exception:
                st.error("General PDF file is encrypted with Password. Please find un-encrypted PDF.")
                st.stop()
        # ---------------------------------------------
                
        total_pages = len(reader.pages)
                
        # Fasa 1: Membaca PDF (0% - 30%)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pdf_text += f"\n\n--- PAGE {i + 1} ---\n{text}"
                    
            prog_val = int(((i + 1) / total_pages) * 30)
            progress_bar.progress(prog_val, text=f"Reading PDF... (Page {i+1}/{total_pages})")
    else:
        progress_bar.progress(30, text="Reading Spec Sheet PDF...")
    return pdf_text

# --- PAPAR KEPUTUSAN IKUT CATEGORY ---
def render_results(job, com, category, raw, dms_df):
    pdf_text, file_names, target_mpn = job["pdf_text"], job["file_names"], job["mpn"]
    extracted_data = copy.deepcopy(raw)
    # Asingkan Designation
    designation_text = extracted_data.pop("Designation", "N/A")
    if isinstance(designation_text, dict): 
        designation_text = designation_text.get("value", "N/A")
    designation_text = str(designation_text).upper()
            
    # --- ASINGKAN MANUFACTURER ---
    manufacturer_text = extracted_data.pop("Manufacturer", "Unknown")
    if isinstance(manufacturer_text, dict): 
        manufacturer_text = manufacturer_text.get("value", "Unknown")
    # Penapis tegas: nama fail / kandungan PDF mengatasi jawapan AI jika bukti kuat
    is_l = com == "L*"
    is_c = com == "C*"
    if is_l:
        manufacturer_text = resolve_manufacturer_l(manufacturer_text, pdf_text, file_names)
        snap_pick_lists(category, extracted_data)   # jawapan AI -> nilai tepat senarai DMS
    elif is_c:
        manufacturer_text = resolve_manufacturer_c(manufacturer_text, pdf_text, file_names)
        snap_pick_lists_c(category, extracted_data)
        designation_text = clean_designation_c(designation_text)
    else:
        manufacturer_text = detect_manufacturer(pdf_text, file_names) or manufacturer_text
    # -----------------------------
            
    if category == RESISTOR:
        # --- ASINGKAN COMMODITY GROUP ---
        cg_options = {
            "RG": "resistor - fixed value",
            "RK": "resistor - PTC, NTC, varistor",
            "RN": "resistor - network",
            "RR": "resistor - adjustable wire resistor",
            "RS": "resistor - potentiometer",
            "RT": "resistor - attenuator, termination",
            "RX": "resistor - unencapsulated chip",
            "RZ": "accessory for resistors",
        }
        cg_raw = extracted_data.pop("Commodity Group", "Unknown")
        if isinstance(cg_raw, dict):
            cg_raw = cg_raw.get("value", "Unknown")
        cg_code = str(cg_raw).strip().upper()[:2]
        if cg_code not in cg_options:
            cg_code = "Unknown"
        cg_code = detect_commodity_group(pdf_text, file_names, cg_code, quantity_from(extracted_data))
        cg_text = f"{cg_code} ({cg_options[cg_code]})" if cg_code in cg_options else "Unknown"
        # --------------------------------
    elif is_l:
        cg_code, cg_ev = determine_cg_l(category, extracted_data, pdf_text, manufacturer_text)
        cg_text = cg_label(cg_code)
    elif is_c:
        cg_code, cg_ev = determine_cg_c(category, extracted_data, pdf_text)
        cg_text = cg_label_c(cg_code)
    else:
        cg_code = CATEGORIES[category]["cg"]
        cg_text = f"{cg_code} · {category}"
            
    if category == RESISTOR:
        # --- STANDARDIZE RESISTANCE (e.g., R300 -> 0R3) ---
        if "Resistance (Ohm)" in extracted_data and isinstance(extracted_data["Resistance (Ohm)"], dict):
            res_val = str(extracted_data["Resistance (Ohm)"].get("value", "")).upper()
            if res_val and res_val != "N/A":
                original_res = res_val
                    
                # Tambah '0' jika bermula dengan 'R' (contoh: R300 -> 0R300)
                if res_val.startswith("R"):
                    res_val = "0" + res_val
                        
                # Buang sifar di belakang (trailing zeros) jika ada huruf R, K, atau M
                if any(char in res_val for char in ["R", "K", "M"]):
                    res_val = res_val.rstrip("0")
                    
                # Kemaskini jadual UI
                extracted_data["Resistance (Ohm)"]["value"] = res_val
                    
                # Kemaskini Designation supaya sepadan (hanya ubah perkataan rintangan pertama)
                if designation_text.startswith(original_res):
                    designation_text = designation_text.replace(original_res, res_val, 1)
        # -------------------------------------------------
            
    if category == RESISTOR:
        # PENAPIS KETAT: Buang unit /K atau /°C pada PPM
        designation_text = designation_text.replace("PPM/K", "PPM").replace("PPM/°C", "PPM").replace("PPM/C", "PPM")

        # --- PENAPIS KETAT: Buang tag HF dan AQ dari Designation ---
        if "HF" in designation_text and "high frequency" not in pdf_text.lower() and "microwave" not in pdf_text.lower():
            designation_text = designation_text.replace("HF", "")
            
        # Paksa buang AQ dari Designation (kerana ia kini berada di Additional Information)
        designation_text = designation_text.replace("AQ", "").replace("  ", " ").replace("//", "/").strip(" /")
            
    # --- TALLY PACKAGE TYPE ---
    # Paksa 'Package Type (EIA)' menyalin bulat-bulat data dari 'Package Type'
    if "Package Type" in extracted_data and isinstance(extracted_data["Package Type"], dict):
        extracted_data["Package Type (EIA)"] = extracted_data["Package Type"].copy()

    # --- PYTHON MATH OVERRIDE UNTUK POWER ---
    if "Power_Extraction_Logic" in extracted_data:
        power_item = extracted_data["Power_Extraction_Logic"]
        if isinstance(power_item, dict):
            # Gabungkan value & evidence
            power_str = str(power_item.get("value", "")) + " " + str(power_item.get("evidence", ""))
            import re
            # Cari semua corak nombor yang diikuti dengan 'W' (Cth: 1.0 W, 0.65W)
            wattages = re.findall(r"(\d+(?:\.\d+)?)\s*[Ww]", power_str)
            if wattages:
                valid_powers = [float(w) for w in wattages]
                min_power = min(valid_powers)
                max_power = max(valid_powers)
                        
                if "Power Consumption (W)" not in extracted_data or not isinstance(extracted_data["Power Consumption (W)"], dict):
                    extracted_data["Power Consumption (W)"] = {"value": "N/A", "evidence": "N/A", "page": "N/A"}
                        
                extracted_data["Power Consumption (W)"]["value"] = str(min_power)
                extracted_data["Power Consumption (W)"]["evidence"] = f"Min value filtered from: {wattages} W"
                        
                # --- KEMASKINI DESIGNATION ---
                # Jika AI terlanjur letak nilai Extended di Designation, Python akan ganti dengan Standard
                if min_power != max_power:
                    designation_text = designation_text.replace(f"{max_power}W", f"{min_power}W")
                    if max_power.is_integer():
                        designation_text = designation_text.replace(f"{int(max_power)}W", f"{min_power}W")

    # --- PYTHON MATH OVERRIDE UNTUK PITCH ---
    if "Pitch (Footprint) (mm)" in extracted_data:
        pitch_item = extracted_data["Pitch (Footprint) (mm)"]
        if isinstance(pitch_item, dict):
            calc_str = str(pitch_item.get("evidence", ""))
            if "-" in calc_str:
                try:
                    # Bersihkan tag spec sheet dan label formula
                    clean_str = calc_str.replace("(From Spec Sheet)", "").replace("Priority Spec Sheet", "")
                    clean_str = clean_str.replace("Formula:", "").strip(" ()")
                    parts = clean_str.split("-")
                    if len(parts) == 2:
                        pitch_val = float(parts[0].strip()) - float(parts[1].strip())
                        extracted_data["Pitch (Footprint) (mm)"]["value"] = str(round(pitch_val, 4))
                        extracted_data["Pitch (Footprint) (mm)"]["evidence"] = clean_str
                except Exception:
                    pass
            
    # --- PYTHON MATH OVERRIDE UNTUK HEIGHT ---
    if "Height_Calculation_Logic" in extracted_data:
        calc_item = extracted_data["Height_Calculation_Logic"]
        if isinstance(calc_item, dict):
            calc_str = str(calc_item.get("value", ""))
            if "+" in calc_str:
                try:
                    parts = calc_str.split("+")
                    h_max = float(parts[0].strip()) + float(parts[1].strip())
                            
                    if "Height (Max)" not in extracted_data or not isinstance(extracted_data["Height (Max)"], dict):
                        extracted_data["Height (Max)"] = {"value": "N/A", "evidence": "N/A", "page": "N/A"}
                            
                    extracted_data["Height (Max)"]["value"] = str(round(h_max, 4))
                    extracted_data["Height (Max)"]["evidence"] = calc_str
                except Exception:
                    pass
                            
    # --- TALLY SUHU (RF): ambient temp = Operating Temperature dalam tab Top ---
    if category.startswith("RF ") or category == "Directional Coupler":
        for amb, top in (("Min. ambient temp. (°C)", "Operating Temperature (Min) (°C)"),
                         ("Max. ambient temp. (°C)", "Operating Temperature (Max) (°C)")):
            t_item = extracted_data.get(top)
            if isinstance(t_item, dict) and str(t_item.get("value", "N/A")).strip() not in ("", "N/A"):
                extracted_data[amb] = dict(t_item)
                            
    # Buang kertas conteng AI dari paparan jadual
    extracted_data.pop("TCR_Calculation_Logic", None)
    extracted_data.pop("Resistance_Calculation_Logic", None)
    extracted_data.pop("Row_Data_Extraction", None)
    extracted_data.pop("Power_Extraction_Logic", None)
    extracted_data.pop("Pitch_Calculation_Logic", None)
    extracted_data.pop("Height_Calculation_Logic", None)
            
    # --- WASHABILITY / VARNISHABILITY ikut PAD-M (kod huruf mengikut Commodity Group) ---
    proc_warnings = apply_processability(extracted_data, cg_code, mpn=target_mpn, designation=designation_text)
    
    # --- ASI DETERMINATION (peraturan ikut Commodity Group; guna nilai akhir selepas semua override) ---
    asi_result = determine_asi_for_cg(cg_code, extracted_data, designation_text, manufacturer_text, pdf_text,
                                      file_names, category, mpn=target_mpn)
    if category == "RF Attenuator" and asi_result.get("rt"):
        designation_text = rt_designation(asi_result["rt"]) or "N/A"
    elif category != RESISTOR and not is_c:   # C*: designation format of the former C* analyzer
        designation_text = "N/A"   # format designation hanya ditakrif untuk Resistor constant (dan RF Attenuator)
            
            
    rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
            
    render_summary(designation_text, manufacturer_text, cg_text, asi_result, target_mpn,
                   rule_applies=(asi_result["label"] != "No rule"), na_text="No rule loaded")
            
    # --- DEFINISI KATEGORI ---
    keys_top = ["Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"]
    keys_library = ["Length (mm)", "Width (mm)", "Height (Max)", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"]
    keys_processability = ["Kind of Mounting", "Washability", "Varnishability",
                           "St. Solder (Standard Solder)", "St. Solder Temp.", "Alt. Solder (Alternate Solder)", "Alt. Solder Temp.",
                           "Rep. Solder (Repair Solder)", "Rep. Solder Temp.", "ESS Suitable",
                           "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)",
                           "Terminal Base", "Terminal Plating", "Recommended Reflow Profil", "Increased Reflow Profile", "ESD"]
    keys_techn_active = ALL_CATEGORIES[category]["techn"]

    def build_table(keys_list, data_dict):
        specs, values, units, evidences, pages = [], [], [], [], []
        for key in keys_list:
            item = data_dict.get(key, {"value": "N/A", "evidence": "N/A", "page": "N/A"})
            if isinstance(item, str):
                val, ev, pg = item, "N/A", "N/A"
            else:
                val = item.get("value", "N/A")
                ev = item.get("evidence", "N/A")
                pg = item.get("page", "N/A")
                        
            # Asingkan Unit
            unit_str = "-"
            if key == "Temperature Coefficient" and val != "N/A":
                if "ppm/°C" in val:
                    val, unit_str = val.replace("ppm/°C", "").strip(), "ppm/°C"
                elif "ppm/K" in val:
                    val, unit_str = val.replace("ppm/K", "").strip(), "ppm/K"
                elif "ppm/C" in val: 
                    val, unit_str = val.replace("ppm/C", "").strip(), "ppm/°C"
                            
            elif "(°C)" in key: key, unit_str = key.replace(" (°C)", ""), "°C"
            elif "(mm)" in key: key, unit_str = key.replace(" (mm)", ""), "mm"
            elif "(Ohm)" in key: key, unit_str = key.replace(" (Ohm)", ""), "Ohm"
            elif "(dB)" in key: key, unit_str = key.replace(" (dB)", ""), "dB"
            elif "(dBm)" in key: key, unit_str = key.replace(" (dBm)", ""), "dBm"
            elif "(Hz)" in key: key, unit_str = key.replace(" (Hz)", ""), "Hz"
            elif "(A)" in key: key, unit_str = key.replace(" (A)", ""), "A"
            elif "(GHz)" in key: key, unit_str = key.replace(" (GHz)", ""), "GHz"
            elif "(%)" in key: key, unit_str = key.replace(" (%)", ""), "%"
            elif "(V)" in key: key, unit_str = key.replace(" (V)", ""), "V"
            elif "(W)" in key: key, unit_str = key.replace(" (W)", ""), "W"
            elif "(H)" in key: key, unit_str = key.replace(" (H)", ""), "H"
            elif "(F)" in key: key, unit_str = key.replace(" (F)", ""), "F"
            elif "(ppm/K)" in key: key, unit_str = key.replace(" (ppm/K)", ""), "ppm/K"
            elif "(s)" in key: key, unit_str = key.replace(" (s)", ""), "s"
            elif "(cycles)" in key: key, unit_str = key.replace(" (cycles)", ""), "cycles"
            elif "(h/°C)" in key: key, unit_str = key.replace(" (h/°C)", ""), "h/°C"
                    
            specs.append(key)
            values.append(val)
            units.append(unit_str)
            evidences.append(ev)
            pages.append(pg)
                    
        return {"Specification": specs, "Extracted Value": values, "Unit": units, "Page": pages, "Source Evidence": evidences}

    # --- TABS UI (keputusan ASI dipaparkan dalam tab Top); L* / C* tiada DMS Check (semak manual dalam DMS) ---
    tab_names = ["Top", "Library", "Processability", "Techn.Parameter", "Alternative"] + ([] if is_l or is_c else ["DMS Check"])
    tabs = st.tabs(tab_names)
    tab1, tab2, tab3, tab4, tab5 = tabs[:5]
    with tab1:
        left, right = st.columns([3, 2])
        with left:
            st.subheader("ASI Result")
            render_asi(asi_result)
        with right:
            st.subheader("Temperature")
            st.table(md_safe(build_table(keys_top, extracted_data)))
    with tab2: st.table(md_safe(build_table(keys_library, extracted_data)))
    with tab3:
        st.table(md_safe(build_table(keys_processability, extracted_data)))
        for w in proc_warnings:
            callout("warning", w)
    with tab4: st.table(md_safe(build_table(keys_techn_active, extracted_data)))
    with tab5: render_alternatives(extracted_data, designation_text, manufacturer_text, asi_result, dms_df, target_mpn, cg_code)
    if not (is_l or is_c):
        with tabs[5]: render_duplicate_check(dms_df, target_mpn, extracted_data, designation_text, cg_code)
            
    # --- JANA FAIL EXCEL (CSV) ---
    all_keys = keys_top + keys_library + keys_processability + keys_techn_active
    all_data = build_table(all_keys, extracted_data)
            
    csv_buffer = io.StringIO()
    csv_buffer.write('\ufeff') 
            
    writer = csv.writer(csv_buffer)
    writer.writerow(["Specification", "Extracted Value", "Unit", "Page", "Source Evidence"]) 
            
    for i in range(len(all_data["Specification"])):
        writer.writerow([all_data["Specification"][i], all_data["Extracted Value"][i], all_data["Unit"][i], all_data["Page"][i], all_data["Source Evidence"][i]])
            
    # Tambah keputusan ASI di hujung CSV
    for row in asi_csv_rows(asi_result):
        writer.writerow(row)
            
    st.divider()
    st.download_button(
        label="📥 Download Report (CSV)",
        data=csv_buffer.getvalue(),
        file_name=f"{rekod_mpn}_Report.csv",
        mime="text/csv"
    )
            

# --- 2. INISIALISASI MEMORI (SESSION STATE) ---
if "reset_key" not in st.session_state:
    st.session_state.reset_key = 0

# --- SIDEBAR: DMS DATABASE ---
dms_df = dms_sidebar()

# --- 3 & 4. COMMODITY, INPUT MPN, RESET & UPLOAD (satu kad) ---
with card("input"):
    # COMMODITY: tab bergaris bawah (Auto-detect lalai; pilih R* / L* / C* untuk tukar)
    with segmented("commodity"):
        st.segmented_control("Commodity", list(COMMODITY_OPTIONS), key="commodity_choice", required=True,
                             label_visibility="collapsed",
                             help="Auto-detect reads the datasheet. Pick R*, L* or C* to override it.")
    c_mpn, c_reset = st.columns([5, 1], vertical_alignment="bottom")
    with c_mpn:
        target_mpn = st.text_input("MPN (optional, recommended for catalogs)", key=f"mpn_{st.session_state.reset_key}")
    with c_reset:
        if st.button("Reset", key="reset_btn", width="stretch"):
            st.session_state.reset_key += 1
            st.session_state.pop("job", None)
            for com in COMMODITIES:
                st.session_state.pop(f"cat_choice_{com}", None)
            st.rerun()

    # --- UI DUAL UPLOAD (dua panel bersebelahan, bertindan di skrin kecil) ---
    with split("uploads"):
        col1, col2 = st.columns(2)
        with col1:
            uploaded_file = st.file_uploader("1. Upload Datasheet PDF (General)", type=["pdf"], key=f"pdf_{st.session_state.reset_key}")
        with col2:
            spec_file = st.file_uploader("2. Upload Spec Sheet PDF (Optional - Priority)", type=["pdf"], key=f"spec_{st.session_state.reset_key}")

    c_btn, c_status = st.columns([1, 4], vertical_alignment="center")
    status_box = c_status.empty()
    if uploaded_file is not None or spec_file is not None:
        with c_btn:
            run_extract = st.button("Extract Data", type="primary", width="stretch")
        if run_extract:
            progress_bar = status_box.progress(0, text="Starting extraction process...")
            try:
                pdf_text = read_pdfs(uploaded_file, spec_file, progress_bar)
                mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
            
                # --- COMMODITY (R*/L*) dahulu, kemudian CATEGORY dalam commodity itu (pengguna boleh tukar kemudian) ---
                file_names = [f.name for f in (uploaded_file, spec_file) if f is not None]
                auto_com, _ = detect_commodity(pdf_text, file_names)
                com = COMMODITY_OPTIONS[st.session_state.commodity_choice] or auto_com
                category, cat_confident = COMMODITIES[com]["detect"](pdf_text, file_names)
            
                progress_bar.progress(40, text=f"Analyzing datasheet using AI ({com} · {category})... This may take a minute.")
                raw = call_model(build_prompt_any(category, mpn_instruction, pdf_text, com), progress_bar)
                if not raw:
                    st.stop()
            
                # Jika kategori tidak pasti, AI mengesahkan; ekstrak semula hanya jika AI nampak kategori lain
                cats = COMMODITIES[com]["categories"]
                if category == COMMODITIES[com]["default"] and not cat_confident:
                    ai_cat = raw.get("Category", "")
                    if isinstance(ai_cat, dict):
                        ai_cat = ai_cat.get("value", "")
                    ai_cat = str(ai_cat).strip()
                    if ai_cat in cats and ai_cat != category:
                        progress_bar.progress(60, text=f"Category looks like {ai_cat}: extracting again...")
                        category = ai_cat
                        raw = call_model(build_prompt_any(category, mpn_instruction, pdf_text, com), progress_bar)
                        if not raw:
                            st.stop()
                raw.pop("Category", None)
            
                # Simpan kerja supaya menukar Commodity / Category tidak perlu muat naik semula
                st.session_state["job"] = {"pdf_text": pdf_text, "file_names": file_names, "mpn": target_mpn,
                                           "mpn_instruction": mpn_instruction, "auto_commodity": auto_com,
                                           "auto_cat": {com: category}, "raw": {f"{com}|{category}": raw}}
                st.session_state[f"cat_choice_{com}"] = category   # lalai = keputusan AI
                progress_bar.progress(100, text="Done!")
                time.sleep(0.5)
                status_box.empty()
                st.session_state["_rerun"] = True   # kemaskini tajuk / commodity di baris atas
            except Exception as e:
                st.error(f"Error Happened!: {e}")

if st.session_state.pop("_rerun", False):
    st.rerun()

job = st.session_state.get("job")
if job:
    with card("results"):
        com = effective_commodity()
        cats = COMMODITIES[com]["categories"]
        # kategori lalai untuk commodity yang baru dipilih: kata kunci sahaja (tiada panggilan AI)
        if com not in job["auto_cat"]:
            job["auto_cat"][com] = COMMODITIES[com]["detect"](job["pdf_text"], job["file_names"])[0]
        cat_key = f"cat_choice_{com}"
        if st.session_state.get(cat_key) not in cats:
            st.session_state[cat_key] = job["auto_cat"][com]

        # --- DROPDOWN CATEGORY: lalai ikut AI, pengguna boleh tukar jika AI tersilap ---
        c_cat, c_note = st.columns([2, 3], vertical_alignment="bottom")
        with c_cat:
            chosen = st.selectbox(f"Category ({com})", list(cats), key=cat_key)
        with c_note:
            com_txt = (f"{com} auto-detected" if COMMODITY_OPTIONS[st.session_state.commodity_choice] is None
                       else f"{com} chosen manually (auto-detect: {job['auto_commodity']})")
            ai = html.escape(job["auto_cat"][com])
            text = (f"✅ Extraction complete · {com_txt} · category detected: {ai}" if chosen == job["auto_cat"][com]
                    else f"✏️ Manual category · {com_txt} · detected: {ai}")
            st.markdown(f'<p class="status-line">{text}</p>', unsafe_allow_html=True)
    
        # ekstrak untuk Category yang dipilih hanya sekali (hasil disimpan, ikut commodity + category)
        raw_key = f"{com}|{chosen}"
        if raw_key not in job["raw"]:
            holder = st.empty()
            pb = holder.progress(0, text=f"Extracting as {chosen}...")
            try:
                new_raw = call_model(build_prompt_any(chosen, job["mpn_instruction"], job["pdf_text"], com), pb)
                if new_raw:
                    new_raw.pop("Category", None)
                    job["raw"][raw_key] = new_raw
            except Exception as e:
                st.error(f"Error Happened!: {e}")
            holder.empty()
    
        if raw_key in job["raw"]:
            try:
                render_results(job, com, chosen, job["raw"][raw_key], dms_df)
            except Exception as e:
                st.error(f"Error Happened!: {e}")
