import streamlit as st
import pandas as pd
import base64
import ITC_classifier
import os
import time

# --- Best Heading Suggestions ---
# 1. ITC Classification Assistance
# 2. ITC Eligibility Classifier
# 3. GST ITC Claim Helper
# 4. Input Tax Credit Analyzer
# 5. ITC Categorization Tool
# I will use "ITC Classification Assistance" for this code.

st.set_page_config(
    page_title="ITC Classification Assistance",
    layout="centered"
)

# --- Background Colors ---
# These are just some ideas. You can easily find more hex codes online.
# The `st.markdown` with `style` is a simple way to add a custom background.

background_color = "#f0f2f6"  # A light, professional grey
# background_color = "#e6f2ff"  # A light blue
# background_color = "#f2e6ff"  # A light purple

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css?family=Roboto:400,700');

html, body, [class*="css"] {
    font-family: 'Roboto', sans-serif;
    font-size: 32px;
}
h1 {
    font-family: 'Roboto', sans-serif;
    font-size: 2.5rem;
}
</style>
""", unsafe_allow_html=True)


# --- Main Application ---
st.title("ITC Classification Assistance")
st.markdown("---")

# --- Input Section ---
st.header("Enter Transaction Details")

col1, col2 = st.columns(2)

with col1:
    material_description = st.text_input("Material Description", placeholder="e.g., Plastic pellets, Machine parts")
    product_hsn = st.text_input("Product HSN", placeholder="e.g., 8479.90.90")

with col2:
    nature_of_transaction = st.text_input("Nature of Transaction", placeholder="e.g., Domestic, imports")
    capital_goods = st.selectbox(
        "Capital Goods",
        ("Select an option", "Y", "N")
    )

if st.button("Submit for Classification"):
    if material_description and product_hsn and nature_of_transaction and capital_goods != "Select an option":
        st.success(f"Classification request for '{material_description}' submitted!")
        st.write(f"**AI result:**")
        results_text=''
        results_text=ITC_classifier.main(material_description,product_hsn,nature_of_transaction,capital_goods)
        st.session_state["search_results"] = results_text
        # Add your classification logic here
    else:
        st.warning("Please fill in all the details before submitting.")


    
    

# Use session state to persist the text area content across reruns
if "search_results" in st.session_state:
    st.text_area(
        "Individual Search Results",
        st.session_state["search_results"],
        height=400
    )

st.markdown("---")

# --- Button Section ---
st.header("Download Template")

col3, col4 = st.columns([1, 4])  # This creates a vertical-like spacing for the button

st.header("Upload a File")
uploaded_file = st.file_uploader("Choose a file")

if uploaded_file is not None:
    # Read the file and display its contents in the text area
    st.success("File uploaded successfully!")

with col4:
    st.write("") # Just for vertical spacing
    download_template_button = st.download_button(
        label="Download Template",
        data="Nature of Transaction,Capital Goods,HSN Code,Material Description,GST Status", # Simple CSV content
        file_name="itc_template.csv",
        mime="text/csv"
    )

# --- (Optional) Logic for the buttons ---
# if bulk_upload_button:
#     st.info("Bulk upload functionality would be implemented here.")

if download_template_button:
    st.success("Template file is being downloaded.")

# --- (Optional) Submit button for the single entry ---

if st.button("Upload bulk data"):
    if uploaded_file:
        st.success(f" Please hold on ..  we are processing..")
        with st.spinner("Processing... Please wait."):
            time.sleep(5)
        resp=ITC_classifier.classify_itc_from_excel(uploaded_file)
        if resp=='success':
            st.success(f"Amigo friend, File is ready in your download folder..enjoy!!.", icon="🎉")
        else:
            st.warning("something went wrong")




        
        # Add your classification logic here
    else:
        st.warning("Please fill in all the details before submitting.")


st.markdown("---")


