import pandas as pd
import json
import os, io
import requests
import re
from typing import Dict, Any, List
import streamlit as st

# --- CONFIGURATION ---
# Use Streamlit secrets for a secure way to handle credentials
AZURE_OPENAI_API_KEY = st.secrets["AZURE_OPENAI_API_KEY"]
AZURE_OPENAI_ENDPOINT = "https://gta-openai.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT_NAME = "GTA-OPENAI"

# --- FILE PATHS ---
# Use relative paths for files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(BASE_DIR, "Rules")
HSN_TARIFF_CSV_PATH = os.path.join(BASE_DIR, "pv_bcd_tariff_202506231736.csv")
PROCESSED_RULES_JSON_PATH = os.path.join(RULES_DIR, "rules.json")

# --- GLOBAL DATA ---
HSN_TARIFF_DATA = None

# --- HELPER FUNCTIONS ---

def load_hsn_tariff_data():
    """Loads the HSN tariff data from a CSV file into a global DataFrame."""
    global HSN_TARIFF_DATA
    try:
        if os.path.exists(HSN_TARIFF_CSV_PATH):
            HSN_TARIFF_DATA = pd.read_csv(HSN_TARIFF_CSV_PATH, dtype=str)
            st.success(f"HSN tariff data loaded from '{HSN_TARIFF_CSV_PATH}'.")
            return True
        else:
            st.error(f"Error: HSN tariff CSV file not found at '{HSN_TARIFF_CSV_PATH}'.")
            return False
    except Exception as e:
        st.error(f"An error occurred while loading the HSN tariff CSV: {e}")
        return False

def get_hsn_description(hsn_code: str) -> str:
    """Fetches the HSN description from the loaded tariff data."""
    if HSN_TARIFF_DATA is None or HSN_TARIFF_DATA.empty:
        return "HSN tariff data not loaded."
    if not isinstance(hsn_code, str):
        return "Invalid HSN code (not a string)."
    
    descriptions = []
    
    def find_desc(code):
        try:
            return HSN_TARIFF_DATA.loc[HSN_TARIFF_DATA["hsn"] == code, 'desc'].iloc[0]
        except (IndexError, KeyError):
            return None
    
    desc_8 = find_desc(hsn_code[:8])
    if desc_8: descriptions.append(desc_8)
    
    if desc_8 and "other" in desc_8.lower():
        desc_6 = find_desc(hsn_code[:6])
        if desc_6: descriptions.append(desc_6)
        
        desc_4 = find_desc(hsn_code[:4])
        if desc_4: descriptions.append(desc_4)
        
    if not descriptions:
        return "Description not found for this HSN code."
        
    return " ".join(dict.fromkeys(descriptions))

def process_rule_book(excel_path: str):
    """Reads the Excel rule book and saves it as a JSON file."""
    if not os.path.exists(excel_path):
        st.error(f"Error: Rule book Excel file not found at '{excel_path}'.")
        return
    
    try:
        df = pd.read_excel(excel_path)
        rules_list = df.to_dict('records')
        
        # Save to a temporary in-memory JSON to avoid file system issues on Streamlit Cloud
        json_buffer = io.StringIO()
        json.dump(rules_list, json_buffer, indent=4)
        json_buffer.seek(0)
        
        st.session_state['rules_json'] = json_buffer.getvalue()
        st.success("Rule book successfully processed.")
    except Exception as e:
        st.error(f"An error occurred while processing the Excel file: {e}")

def get_azure_openai_response(prompt: str) -> str:
    """Calls the Azure OpenAI API with the given prompt."""
    if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME]):
        return "Error: Azure OpenAI credentials are not configured. Please add them to Streamlit secrets."
    
    url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version=2024-02-15-preview"
    headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_API_KEY}
    payload = {
        "messages": [
            {"role": "system", "content": "You are an expert on tax and ITC classification. You must provide a clear 'Yes' or 'No' answer, followed by a brief justification."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except requests.exceptions.RequestException as e:
        st.error(f"An error occurred during the API call: {e}")
        return f"Error: API call failed. Details: {e}"

def get_classification_for_item(item_data: pd.Series, rules: List[Dict[str, Any]]) -> str:
    # Your existing function, no changes needed here
    # ...
    material_description = item_data.get('Material Description', 'N/A')
    product_hsn = item_data.get('HSN Code', 'N/A')
    nature_transaction = item_data.get('Nature of Transaction', 'N/A')
    capital_goods = item_data.get('Capital Goods', 'N/A')
    gst_status = item_data.get('GST Statuss', 'N/A')
    hsn_description = get_hsn_description(str(product_hsn))
    rules_text = json.dumps(rules, indent=2)

    prompt = f"""
        You are an expert on tax and Input Tax Credit (ITC) classification. Your task is to determine the eligibility of ITC for a given item. We are doing it for port operator and logistics company - Ports & Terminals - Cargo handling expertise.
        First, you must use the provided set of rules. If a definitive classification cannot be made using these rules, you may then use your extensive knowledge of GST laws, including Indian Trade Classification (ITC-HS) and Section 17(5) of the CGST Act, to provide the most accurate assessment.
        RULES:
        ```json
        {rules_text}
        ```
        ... (rest of your prompt)
        """
    return get_azure_openai_response(prompt)


def parse_ai_response_revised(response_text: str) -> Dict[str, str]:
    # Your existing function, no changes needed here
    # ...
    if not response_text:
        return {
            "Answer": "Error: Empty AI Response", "Confidence Score": "N/A",
            "Justification": "N/A", "Questions for Clarification": "N/A"
        }

    parsed_data = {
        "Answer": "Not Found", "Confidence Score": "Not Found",
        "Justification": "Not Found", "Questions for Clarification": "Not Found"
    }

    answer_match = re.search(r'\b(Yes|No)\b', response_text, re.IGNORECASE)
    if answer_match:
        parsed_data["Answer"] = answer_match.group(1).capitalize()

    headers = [
        "Confidence Score", "Justification",
        "Questions for Clarification", "Relevant Questions"
    ]
    split_pattern = re.compile(r'\b(' + '|'.join(headers) + r')\b\s*:', re.IGNORECASE)
    parts = split_pattern.split(response_text)
    initial_text = parts[0]

    for i in range(1, len(parts), 2):
        header = parts[i].strip().lower()
        content = parts[i + 1].strip()

        if "confidence" in header:
            parsed_data["Confidence Score"] = content
        elif "justification" in header:
            if parsed_data["Justification"] == "Not Found":
                parsed_data["Justification"] = content
        elif "questions" in header:
            parsed_data["Questions for Clarification"] = content

    if parsed_data["Justification"] == "Not Found":
        temp_justification = re.sub(r'Answer\s*:\s*\b(Yes|No)\b', '', initial_text, flags=re.IGNORECASE).strip()
        if answer_match:
            temp_justification = temp_justification.replace(answer_match.group(0), '', 1).strip()
        if temp_justification:
            parsed_data["Justification"] = temp_justification

    for key, value in parsed_data.items():
        if value == "Not Found":
            parsed_data[key] = "N/A"

    return parsed_data


# --- MAIN LOGIC ---

def classify_itc_from_excel(input_df):
    """Main function to load data, classify each item, and save results."""
    
    if 'rules_json' not in st.session_state:
        st.error("Rules not loaded. Please process the rule book first.")
        return
        
    rules = json.loads(st.session_state['rules_json'])
    
    df = input_df.copy().fillna('N/A')
    
    parsed_results = []
    total_rows = len(df)
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for index, row in df.iterrows():
        status_text.text(f"Processing row {index + 1}/{total_rows}: {row.get('Material Description', 'N/A')}")
        
        raw_result = get_classification_for_item(row, rules)
        
        # Parse the AI response
        parsed_data = parse_ai_response_revised(raw_result)
        parsed_results.append(parsed_data)
        
        progress_bar.progress((index + 1) / total_rows)

    status_text.text("Combining results with input data...")
    results_df = pd.DataFrame(parsed_results).rename(columns={
        "Answer": "ITC_Answer", "Confidence Score": "ITC_Confidence_Score",
        "Justification": "ITC_Justification", "Questions for Clarification": "ITC_Clarification_Questions"
    })
    
    final_df = pd.concat([df.reset_index(drop=True), results_df.reset_index(drop=True)], axis=1)
    
    return final_df

# ==============================================================================
# STREAMLIT UI CODE
# ==============================================================================

def main_app():
    st.set_page_config(page_title="ITC Classification Tool", layout="wide")
    st.title("GST ITC Classification Tool 🤖")
    
    st.markdown("""
    This application helps classify the eligibility of Input Tax Credit (ITC) for your transactions.
    
    1.  **Upload** your `rulebook.xlsx` and `PO and Work Order Data.xlsx`.
    2.  **Process** the rule book.
    3.  **Classify** your data.
    4.  **Download** the classified output.
    """)
    
    st.sidebar.header("Step 1: Upload Files")
    rulebook_file = st.sidebar.file_uploader("Upload Rule Book (rulebook.xlsx)", type=["xlsx"])
    data_file = st.sidebar.file_uploader("Upload Data to Classify (Excel/CSV)", type=["xlsx", "csv"])

    # --- Processing the Rule Book ---
    if st.sidebar.button("Process Rule Book"):
        if rulebook_file is not None:
            # Save the uploaded file temporarily to process it
            with open("rulebook_temp.xlsx", "wb") as f:
                f.write(rulebook_file.getbuffer())
            
            process_rule_book("rulebook_temp.xlsx")
            os.remove("rulebook_temp.xlsx")
        else:
            st.sidebar.error("Please upload a rulebook.xlsx file first.")

    # --- Classifying Data ---
    st.sidebar.header("Step 2: Classify Data")
    if st.sidebar.button("Classify Data"):
        if 'rules_json' not in st.session_state:
            st.error("Please process the rule book first.")
        elif data_file is not None:
            st.info("Classifying items... This may take some time.")
            
            # Read the uploaded data file
            try:
                if data_file.name.endswith('.csv'):
                    input_df = pd.read_csv(data_file, dtype=str, encoding='iso-8859-1')
                else:
                    input_df = pd.read_excel(data_file, dtype=str)
                
                final_df = classify_itc_from_excel(input_df)
                
                if final_df is not None:
                    st.success("Classification complete!")
                    st.dataframe(final_df)
                    
                    # Create the in-memory Excel file for download
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                        final_df.to_excel(writer, index=False, sheet_name='ITC Classification')
                    excel_buffer.seek(0)
                    
                    # Display the download button
                    st.download_button(
                        label="📥 Download Classified Data as Excel",
                        data=excel_buffer,
                        file_name="classified_output.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            except Exception as e:
                st.error(f"An error occurred during classification: {e}")
        else:
            st.sidebar.error("Please upload a data file to classify.")
            
    st.markdown("---")
    st.header("Single Item Classification")
    material_description = st.text_input("Material Description")
    product_hsn = st.text_input("HSN Code")
    nature_transaction = st.text_input("Nature of Transaction")
    capital_goods = st.selectbox("Capital Goods?", ["Yes", "No"])
    
    if st.button("Classify Single Item"):
        if material_description and product_hsn and nature_transaction and capital_goods:
            if not load_hsn_tariff_data():
                st.stop()
            if 'rules_json' not in st.session_state:
                st.error("Please process the rule book first to enable single item classification.")
            else:
                rules = json.loads(st.session_state['rules_json'])
                
                # Create a temporary Series for a single item
                item_data = pd.Series({
                    'Material Description': material_description,
                    'HSN Code': product_hsn,
                    'Nature of Transaction': nature_transaction,
                    'Capital Goods': capital_goods
                })
                
                with st.spinner('Classifying...'):
                    raw_result = get_classification_for_item(item_data, rules)
                
                parsed_data = parse_ai_response_revised(raw_result)
                
                st.subheader("Classification Result")
                st.write(f"**ITC Eligibility:** {parsed_data.get('Answer', 'N/A')}")
                st.write(f"**Confidence Score:** {parsed_data.get('Confidence Score', 'N/A')}")
                st.write(f"**Justification:** {parsed_data.get('Justification', 'N/A')}")
                st.write(f"**Questions for Clarification:** {parsed_data.get('Questions for Clarification', 'N/A')}")
        else:
            st.warning("Please fill in all fields to classify a single item.")

if __name__ == "__main__":
    main_app()
