import pandas as pd
import json
import os
import requests
import re
from typing import Dict, Any, List

# --- CONFIGURATION ---
# IMPORTANT: Replace with your actual Azure OpenAI details
AZURE_OPENAI_API_KEY =st.secrets["AZURE_OPENAI_API_KEY"]
#AZURE_OPENAI_API_KEY = os.environ.get('AZURE_OPENAI_API_KEY')
AZURE_OPENAI_ENDPOINT = "https://gta-openai.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT_NAME = "GTA-OPENAI"

# --- FILE PATHS ---
base_path = os.getcwd()

# Create directories if they don't exist
os.makedirs(os.path.join(base_path, "Rules"), exist_ok=True)
os.makedirs(os.path.join(base_path, "input"), exist_ok=True)
os.makedirs(os.path.join(base_path, "output"), exist_ok=True)

EXCEL_RULE_BOOK_PATH = os.path.join(base_path, "rulebook.xlsx")
PROCESSED_RULES_JSON_PATH = os.path.join(base_path, "rules.json")
HSN_TARIFF_CSV_PATH = os.path.join(base_path, "pv_bcd_tariff_202506231736.csv")

INPUT_DATA_EXCEL_PATH = os.path.join(base_path, "PO and Work Order Data 1.xlsx")
OUTPUT_DATA_EXCEL_PATH = os.path.join(base_path, "classified_output.xlsx")

# --- GLOBAL DATA ---
HSN_TARIFF_DATA = None


# --- HELPER FUNCTIONS ---

def load_hsn_tariff_data():
    """Loads the HSN tariff data from a CSV file into a global DataFrame."""
    global HSN_TARIFF_DATA
    if not os.path.exists(HSN_TARIFF_CSV_PATH):
        print(f"Error: HSN tariff CSV file not found at '{HSN_TARIFF_CSV_PATH}'.")
        print("Please update the HSN_TARIFF_CSV_PATH variable in the script.")
        return False
    try:
        HSN_TARIFF_DATA = pd.read_csv(HSN_TARIFF_CSV_PATH, dtype=str)
        print(f"HSN tariff data loaded from '{HSN_TARIFF_CSV_PATH}'.")
        return True
    except Exception as e:
        print(f"An error occurred while loading the HSN tariff CSV: {e}")
        return False


def get_hsn_description(hsn_code: str) -> str:
    """Fetches the HSN description from the loaded tariff data."""
    if HSN_TARIFF_DATA is None or HSN_TARIFF_DATA.empty: return "HSN tariff data not loaded."
    if not isinstance(hsn_code, str): return "Invalid HSN code (not a string)."
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
    if not descriptions: return "Description not found for this HSN code."
    return " ".join(dict.fromkeys(descriptions))


def process_rule_book(excel_path: str, json_path: str):
    """Reads the Excel rule book and saves it as a JSON file."""
    if not os.path.exists(excel_path): print(f"Error: Rule book Excel file not found at '{excel_path}'."); return
    print(f"Processing rule book from '{excel_path}'...")
    try:
        df = pd.read_excel(excel_path)
        rules_list = df.to_dict('records')
        with open(json_path, 'w') as f:
            json.dump(rules_list, f, indent=4)
        print(f"Rule book successfully processed and saved to '{json_path}'.")
    except Exception as e:
        print(f"An error occurred while processing the Excel file: {e}")


def get_azure_openai_response(prompt: str) -> str:
    """Calls the Azure OpenAI API with the given prompt."""
    if "YOUR_AZURE" in AZURE_OPENAI_API_KEY or not all(
            [AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME]):
        return "Error: Azure OpenAI credentials are not configured. Please update the configuration section."
    url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version=2024-02-15-preview"
    headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_API_KEY}
    payload = {
        "messages": [{"role": "system",
                      "content": "You are an expert on tax and ITC classification. You must provide a clear 'Yes' or 'No' answer, followed by a brief justification."},
                     {"role": "user", "content": prompt}],
        "temperature": 0.0, "max_tokens": 500
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the API call: {e}")
        return f"Error: API call failed. Details: {e}"


def get_classification_for_item(item_data: pd.Series, rules: List[Dict[str, Any]]) -> str:
    """Constructs your preferred prompt and gets the classification string for a single item."""
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
        Rules for ITC Eligibility
        Here is a list of rules from a rule book. Each rule is a JSON object with fields like Nature of Supplier, Type of Supply, Nature of Expense, Type, Intended Use, Category, Section Reference, and ITC Eligibility.
        
        Now, here is a new item that needs to be classified based on these rules:
        - Material Description: {material_description}
        - HSN Description: {hsn_description}
        - Nature of transaction : {nature_transaction}
        - Capital goods : {capital_goods}

        New Item for Classification
        Here are the details of a new item that needs to be classified.

        Material Description: {material_description}

        HSN Description: {hsn_description}

        Nature of transaction: {nature_transaction}

        Capital goods: {capital_goods}

        Classification Process
        Follow this step-by-step procedure to determine the ITC eligibility:

        Attribute Extraction: From the Material Description, HSN Description, Nature of transaction, and Capital goods of the new item, extract relevant attributes. Map these to the rulebook's columns:

        Type of Supply: Derive from Material Description or HSN Description. If a specific type cannot be determined, treat it as "Any."

        Nature of Expense: Use the Capital goods field. If "Yes," the Nature of Expense is "Capitalised." If "No," it is "Revenue."

        Other Attributes: Identify values for Nature of Supplier, Type, Intended Use, and Category from the descriptions and transaction details.

        Please make note of below suggestions too:
        1) If Intended use cannot be determined as per rule book then assume that all material and services are in furtherance of business
        2) In case of motor vehicles - AI to first determine whether it is a passenger vehicle or commercial vehicle for movement of goods.If it is later,then no need to check for seating capacity.

        Rule Matching (Internal Rules First):

        Compare the extracted attributes to the rules in the provided JSON. Find the most specific rule that matches the highest number of attributes.

        Once a matching rule is found, determine the ITC Eligibility ("Yes" or "No").

        External Knowledge (If Rules Are Insufficient):

        If no specific rule can be found within the provided JSON, use your external knowledge of GST laws to determine the ITC applicability.

        Refer to common blocked credits under Section 17(5) of the CGST Act (e.g., motor vehicles, food and beverages, construction services for immovable property) and other relevant regulations.
        However in case of construction of immovable property- repair and maintenance of Building, Plant and Machinary, Civil work etc. whenever not capitalised ITC should be allowed .
        

        **OUTPUT FORMAT (MUST be followed exactly):**
        Answer: [Yes/No]
        Confidence Score: [Provide a percentage, e.g., 95%]
        Justification: [Provide a brief and precise justification for your answer, referencing the rules or item details.]
        Questions for Clarification(Formulate relevant questions to ask as per rule book):
        1. [First question]
        2. [Second question]
        3. [Third question]
        """
    return get_azure_openai_response(prompt)


# ==============================================================================
#  NEW, HIGHLY ROBUST PARSING FUNCTION
# ==============================================================================
def parse_ai_response_revised(response_text: str) -> Dict[str, str]:
    """
    Parses a text response from the AI into a dictionary by splitting it into sections.
    This is more robust against formatting variations than the previous version.
    """
    if not response_text:
        return {
            "Answer": "Error: Empty AI Response", "Confidence Score": "N/A",
            "Justification": "N/A", "Questions for Clarification": "N/A"
        }

    parsed_data = {
        "Answer": "Not Found", "Confidence Score": "Not Found",
        "Justification": "Not Found", "Questions for Clarification": "Not Found"
    }

    # Find the initial Yes/No answer, which is usually first.
    answer_match = re.search(r'\b(Yes|No)\b', response_text, re.IGNORECASE)
    if answer_match:
        parsed_data["Answer"] = answer_match.group(1).capitalize()

    # Define the headers that divide the text into sections.
    # The order matters for how we associate text before the first header.
    headers = [
        "Confidence Score", "Justification",
        "Questions for Clarification", "Relevant Questions"
    ]
    # Create a regex pattern to split the text by these headers.
    # The pattern looks for a header followed by a colon.
    split_pattern = re.compile(r'\b(' + '|'.join(headers) + r')\b\s*:', re.IGNORECASE)
    parts = split_pattern.split(response_text)

    # The first part of the split is the text before any known headers.
    # It might contain the answer and/or part of the justification if headers are missing.
    initial_text = parts[0]

    # Process the remaining parts, which come in pairs of (header, content).
    # e.g., ['Confidence Score', '95%', 'Justification', '... a good reason ...']
    # We zip them together to create (key, value) pairs.
    for i in range(1, len(parts), 2):
        header = parts[i].strip().lower()
        content = parts[i + 1].strip()

        if "confidence" in header:
            parsed_data["Confidence Score"] = content
        elif "justification" in header:
            # If justification is still "Not Found", this is the main justification
            if parsed_data["Justification"] == "Not Found":
                parsed_data["Justification"] = content
        elif "questions" in header:
            parsed_data["Questions for Clarification"] = content

    # --- Final Cleanup ---
    # If Justification is still not found, it might be in the initial text block,
    # after the "Answer". We can extract it.
    if parsed_data["Justification"] == "Not Found":
        # Remove the found Answer and any "Answer:" header from the initial text
        temp_justification = re.sub(r'Answer\s*:\s*\b(Yes|No)\b', '', initial_text, flags=re.IGNORECASE).strip()
        if answer_match:
            temp_justification = temp_justification.replace(answer_match.group(0), '', 1).strip()
        if temp_justification:
            parsed_data["Justification"] = temp_justification

    # Change any remaining "Not Found" to "N/A" for cleaner output.
    for key, value in parsed_data.items():
        if value == "Not Found":
            parsed_data[key] = "N/A"

    return parsed_data


# ==============================================================================
#  (Original parsing function for reference - NOT USED)
# ==============================================================================
def parse_ai_response_original(response_text: str) -> Dict[str, str]:
    # This is the original function that was causing issues.
    # It is kept here for comparison but is not called by the main script.
    parsed_data = {
        "Answer": "Parsing Error", "Confidence Score": "Parsing Error",
        "Justification": "Parsing Error", "Questions for Clarification": "Parsing Error"
    }

    if not response_text:
        return parsed_data

    # --- 1. Find Answer ---
    answer_match = re.search(r'\b(Yes|No)\b', response_text, re.IGNORECASE)
    if answer_match:
        parsed_data["Answer"] = answer_match.group(1).capitalize()

    # --- 2. Find Confidence Score ---
    confidence_match = re.search(r'(Confidence Score|Confidence)\s*:\s*(.*?)(?:\n|$)', response_text, re.IGNORECASE)
    if confidence_match:
        parsed_data["Confidence Score"] = confidence_match.group(2).strip()

    # --- 3. Find Questions for Clarification ---
    # THIS IS THE PROBLEMATIC REGEX
    questions_match = re.search(r'(Questions for Clarification|Relevant Questions|Questions)\s*:|^\s*1\s*[\.\)]',
                                response_text, re.IGNORECASE | re.MULTILINE)
    questions_content = ""
    if questions_match:
        questions_start_index = questions_match.start()
        questions_content = response_text[questions_start_index:].strip()
        parsed_data["Questions for Clarification"] = questions_content

    # --- 4. Find Justification (the part in the middle) ---
    start_index = 0
    end_index = len(response_text)

    if confidence_match:
        start_index = confidence_match.end()
    elif answer_match:
        start_index = answer_match.end()

    if questions_match:
        end_index = questions_match.start()

    justification_content = response_text[start_index:end_index].strip()
    justification_content = re.sub(r'^\s*(Justification|Confidence Score|Confidence)\s*:', '', justification_content,
                                   flags=re.IGNORECASE).strip()

    if parsed_data["Confidence Score"] != "Parsing Error":
        justification_content = justification_content.replace(parsed_data["Confidence Score"], "").strip()

    if justification_content:
        parsed_data["Justification"] = justification_content
    elif parsed_data["Justification"] == "Parsing Error" and (
            parsed_data["Answer"] != "Parsing Error" or parsed_data["Questions for Clarification"] != "Parsing Error"):
        parsed_data["Justification"] = "N/A"

    return parsed_data


# --- MAIN LOGIC ---

def classify_itc_from_excel(INPUT_DATA_EXCEL_PATH):
    if not load_hsn_tariff_data(): return



    """Main function to load data, classify each item, and save results."""
    #downloadfolder=os.path.join(os.path.join(os.environ['USERPROFILE']), 'Downloads')
    OUTPUT_DATA_EXCEL_PATH=os.path.join("classified_output.xlsx")
    PROCESSED_RULES_JSON_PATH=os.path.join(os.getcwd(),"Rules")
    PROCESSED_RULES_JSON_PATH=os.path.join(PROCESSED_RULES_JSON_PATH,"rules.json")
    if not os.path.exists(PROCESSED_RULES_JSON_PATH): print(
        f"Error: Rules file '{PROCESSED_RULES_JSON_PATH}' not found."); return


    print(f"Loading rules from '{PROCESSED_RULES_JSON_PATH}'...")
    with open(PROCESSED_RULES_JSON_PATH, 'r') as f:
        rules = json.load(f)

    print(f"Loading input data from '{INPUT_DATA_EXCEL_PATH}'...")
    try:
        # Use dtype=str to prevent pandas from auto-interpreting types like HSN codes
        df = pd.read_csv(INPUT_DATA_EXCEL_PATH, dtype=str,encoding='iso-8859-1').fillna('N/A')
    except Exception as e:
        print(f"Failed to read input Excel file: {e}");
        return

    parsed_results = []
    total_rows = len(df)
    print(f"\nStarting classification for {total_rows} items...")

    for index, row in df.iterrows():
        print(f"--- Processing row {index + 1}/{total_rows}: {row.get('Material Description', 'N/A')} ---")

        raw_result = get_classification_for_item(row, rules)
        import time
        time.sleep(0.2)

        print("--- RAW AI RESPONSE (for debugging) ---")
        print(raw_result)
        print("---------------------------------------")

        # *** CALLING THE NEW, REVISED PARSING FUNCTION ***
        parsed_data = parse_ai_response_revised(raw_result)
        parsed_results.append(parsed_data)

        print(f"  - Parsed Answer: {parsed_data.get('Answer', 'N/A')}")
        print(f"  - Parsed Justification: {parsed_data.get('Justification', 'N/A')[:70]}...")  # Print first 70 chars

    print("\nCombining results with input data...")
    results_df = pd.DataFrame(parsed_results).rename(columns={
        "Answer": "ITC_Answer", "Confidence Score": "ITC_Confidence_Score",
        "Justification": "ITC_Justification", "Questions for Clarification": "ITC_Clarification_Questions"
    })

    final_df = pd.concat([df.reset_index(drop=True), results_df.reset_index(drop=True)], axis=1)

    try:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, index=False, sheet_name='ITC Classification')
        excel_buffer.seek(0)
        st.success("Classification complete! Click the button below to download the results.")
        st.download_button(
                    label="Download Classified Data as Excel",
                    data=excel_buffer,
                    file_name="classified_output.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        return "success"
        #final_df.to_excel(OUTPUT_DATA_EXCEL_PATH, index=False)
        return("success")
        print(f"\n--- CLASSIFICATION COMPLETE ---")
        print(f"All items processed. Results saved to '{OUTPUT_DATA_EXCEL_PATH}'.")
    except PermissionError:
        print(f"\nError: Could not save output to '{OUTPUT_DATA_EXCEL_PATH}'. Please close the file if it's open.")
        return("fail")
    except Exception as e:
        print(f"\nAn error occurred while saving the output file: {e}")
        return("fail")


# --- SCRIPT ENTRY POINT ---
def classify_itc(material_description,product_hsn,nature_transaction,capital_goods):
    """
    Main function to load rules, get user input, and classify ITC.
    """
    # Check if the processed rules file exists
    if not os.path.exists(PROCESSED_RULES_JSON_PATH):
        print(f"Processed rules file '{PROCESSED_RULES_JSON_PATH}' not found.")
        print("Please run the script to process the rule book first.")
        return

    # Load the processed rule book from JSON
    print(f"Loading rules from '{PROCESSED_RULES_JSON_PATH}'...")
    with open(PROCESSED_RULES_JSON_PATH, 'r') as f:
        rules = json.load(f)

    # Get user inputs

    # Fetch the HSN description
    hsn_description = get_hsn_description(product_hsn)
    print("hsn_description:" ,hsn_description)

    # Construct the prompt for the LLM
    rules_text = json.dumps(rules, indent=2)
    
    prompt = f"""
    You are an expert on tax and Input Tax Credit (ITC) classification. Your task is to determine the eligibility of ITC for a given item. We are doing it for port operator and logistics company - Ports & Terminals - Cargo handling expertise.
    First, you must use the provided set of rules. If a definitive classification cannot be made using these rules, you may then use your extensive knowledge of GST laws, including Indian Trade Classification (ITC-HS) and Section 17(5) of the CGST Act, to provide the most accurate assessment.
    RULES:
    ```json
    {rules_text}
    ```
    Rules for ITC Eligibility
    Here is a list of rules from a rule book. Each rule is a JSON object with fields like Nature of Supplier, Type of Supply, Nature of Expense, Type, Intended Use, Category, Section Reference, and ITC Eligibility.
    
    Now, here is a new item that needs to be classified based on these rules:
    - Material Description: {material_description}
    - HSN Description: {hsn_description}
    - Nature of transaction : {nature_transaction}
    - Capital goods : {capital_goods}

    New Item for Classification
    Here are the details of a new item that needs to be classified.

    Material Description: {material_description}

    HSN Description: {hsn_description}

    Nature of transaction: {nature_transaction}

    Capital goods: {capital_goods}

    Classification Process
    Follow this step-by-step procedure to determine the ITC eligibility:

    Attribute Extraction: From the Material Description, HSN Description, Nature of transaction, and Capital goods of the new item, extract relevant attributes. Map these to the rulebook's columns:

    Type of Supply: Derive from Material Description or HSN Description. If a specific type cannot be determined, treat it as "Any."

    Nature of Expense: Use the Capital goods field. If "Yes," the Nature of Expense is "Capitalised." If "No," it is "Revenue."

    Other Attributes: Identify values for Nature of Supplier, Type, Intended Use, and Category from the descriptions and transaction details.

    Please make note of below suggestions too:
    1) If Intended use cannot be determined as per rule book then assume that all material and services are in furtherance of business
    2) In case of motor vehicles - AI to first determine whether it is a passenger vehicle or commercial vehicle for movement of goods.If it is later,
       then no need to check for seating capacity.

    Rule Matching (Internal Rules First):

    Compare the extracted attributes to the rules in the provided JSON. Find the most specific rule that matches the highest number of attributes.

    Once a matching rule is found, determine the ITC Eligibility ("Yes" or "No").

    External Knowledge (If Rules Are Insufficient):

    If no specific rule can be found within the provided JSON, use your external knowledge of GST laws to determine the ITC applicability.

    Refer to common blocked credits under Section 17(5) of the CGST Act (e.g., motor vehicles, food and beverages, construction services for immovable property) and other relevant regulations.
    However in case of construction of immovable property- repair and maintenance of Building, Plant and Machinary, Civil work etc. whenever not capitalised ITC should be allowed .

    Please provide a clear answer of 'Yes' or 'No', along with confidence score followed by a brief and precise justification. 
    Also Formulate 3 most relevant questions to ask as per rule book.
    the user about the material/product description to obtain any  missing or unclear details and it should be related to rule book.Questions should not be about HSN. 
    These questions should help refine the suggestions further and ensure proper classification is identified.
    Stop hullicination as Answers keep on changing with every itertaion. 
    If you used external knowledge, state that a specific rule was not found in the provided list and explain your conclusion based on the relevant GST law (e.g., citing a specific section or rule).
    """
    
    # Get the classification from Azure OpenAI
    itc_result = get_azure_openai_response(prompt)
    
    print("\n--- CLASSIFICATION RESULT ---")
    print(f"Based on the inputs, the classification is: {itc_result}")
    print("--------------------------")

    return(itc_result)
def main(material_description,product_hsn,nature_transaction,capital_goods):
    """The main entry point for the script."""
    print("--- BATCH ITC CLASSIFICATION TOOL ---")
    if not load_hsn_tariff_data(): return

    if not os.path.exists(PROCESSED_RULES_JSON_PATH):
        print(f"\nRules JSON not found at '{PROCESSED_RULES_JSON_PATH}'.")
        if os.path.exists(EXCEL_RULE_BOOK_PATH):
            print(f"Found rule book at '{EXCEL_RULE_BOOK_PATH}'.")
            process_rule_book(EXCEL_RULE_BOOK_PATH, PROCESSED_RULES_JSON_PATH)
        else:
            print(f"Error: Rule book Excel file not found at '{EXCEL_RULE_BOOK_PATH}'.")
            print("Please create the rulebook.xlsx file in the 'Rules' directory.")
            return
    return classify_itc(material_description,product_hsn,nature_transaction,capital_goods)



    











