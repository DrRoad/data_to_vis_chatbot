# production_app.py
import streamlit as st
import pandas as pd
import io
import matplotlib.pyplot as plt
from helpers import *
import firebase_admin
from firebase_admin import credentials, auth, firestore
import stripe
import requests
import json

# Load secrets
stripe_secret_key = st.secrets["stripe_secret_key"]
firebase_service_account_key = json.loads(st.secrets["firebase_service_account_key"])
firebase_api_key = st.secrets["firebase_api_key"]

# Initialize Firebase
def initialize_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_service_account_key)
        firebase_admin.initialize_app(cred)

initialize_firebase()
db = firestore.client()

# Initialize Stripe
stripe.api_key = stripe_secret_key

def create_checkout_session():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'DataChat Access',
                    },
                    'unit_amount': 500,  # Amount in cents ($5.00)
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://localhost:8503',
            cancel_url='http://localhost:8503',
        )
        return session.url
    except Exception as e:
        st.error(f"Error creating checkout session: {e}")
        return None


def execute_and_capture_plot(code):
    try:
        exec(code, globals())
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        return buf
    except SyntaxError as e:
        st.error(f"Failed to generate plot: {e}")
        return None
    except Exception as e:
        st.error(f"Failed to generate plot: {str(e)}")
        return None

def sign_up(email, password):
    try:
        user = auth.create_user(email=email, password=password)
        return user.uid
    except Exception as e:
        st.error(f"Error creating user: {e}")
        return None


def sign_in(email, password):
    try:
        user = auth.get_user_by_email(email)
        custom_token = auth.create_custom_token(user.uid)
        # Exchange the custom token for an ID token
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={firebase_api_key}"
        payload = {
            "token": custom_token.decode('utf-8'),
            "returnSecureToken": True
        }
        response = requests.post(url, json=payload)
        id_token = response.json().get('idToken')
        return id_token
    except Exception as e:
        st.error(f"Error signing in: {e}")
        return None

def sign_out():
    st.session_state["auth_token"] = None

# Authentication
if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = None

if st.session_state["auth_token"] is None:
    auth_mode = st.sidebar.radio("Authentication", ["Sign Up", "Sign In"])

    if auth_mode == "Sign Up":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Sign Up"):
            user_id = sign_up(email, password)
            if user_id:
                st.sidebar.success("Sign Up Successful. Please Sign In.")
    elif auth_mode == "Sign In":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Sign In"):
            auth_token = sign_in(email, password)
            if auth_token:
                st.session_state["auth_token"] = auth_token
                st.experimental_rerun()
else:
    st.sidebar.write("Signed in")
    if st.sidebar.button("Sign Out"):
        sign_out()
        st.experimental_rerun()

    # Add Payment Button
    checkout_url = create_checkout_session()
    if checkout_url:
        st.sidebar.markdown(f"[By Me a Coffee]({checkout_url})", unsafe_allow_html=True)

    with st.sidebar:
        openai_api_key = st.text_input("Please Input OpenAI API Key below:", key="chatbot_api_key", type="password")
        uploaded_file = st.file_uploader(":computer: Load your CSV data file:", type="csv")
        if uploaded_file:
            file_name = uploaded_file.name[:-4].capitalize()
            if "datasets" not in st.session_state:
                st.session_state["datasets"] = {}
            st.session_state["datasets"][file_name] = pd.read_csv(uploaded_file)
            chosen_dataset = file_name
        else:
            chosen_dataset = None

    st.title("💬 Data to Visualisation Chatbot")
    st.caption("An interactive chatbot designed to conduct data analysis and create data visualizations from natural language")

    if "messages" not in st.session_state:
        st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])
        if "image" in msg:
            st.chat_message("assistant").image(msg["image"], caption=msg["prompt"], use_column_width=True)

    st.markdown("---")
    st.markdown("### Prompt Guide")
    st.markdown("- 🗒️ Start with \"Explore:\" to get suggested prompt from ChatGPT")
    st.markdown("- 📉 Start with \"Show:\" to have ChatGPT generate a plot based on your entered prompt")
    st.markdown("- 📖 Say \"Describe it\" to have ChatGPT describe the plot it just generated for you")

    if "vis_code" not in st.session_state:
        st.session_state["vis_code"] = ""

    if prompt := st.chat_input():
        if not openai_api_key:
            st.error("Please add your OpenAI API key to continue.")
        elif chosen_dataset is None:
            st.error("Please upload a CSV file and select a dataset before entering a prompt.")
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.chat_message("user").write(prompt)

            openai.api_key = openai_api_key

            answer = ""
            if prompt.lower().startswith("describe"):
                if st.session_state["vis_code"]:
                    answer = describe_plot(st.session_state["vis_code"], openai_api_key)
                else:
                    st.info("You haven't created any visualization yet!")
                    st.stop()
            elif prompt.lower().startswith("show"):
                primer1, primer2 = get_primer(st.session_state["datasets"][chosen_dataset], f'st.session_state["datasets"]["{chosen_dataset}"]')
                question_to_ask = format_question(primer1, primer2, prompt)
                answer = run_request(question_to_ask, openai_api_key)
                answer = primer2 + answer
                answer = format_response(answer)
            elif "explore" in prompt.lower():
                answer = ask_gpt(describe_dataset(st.session_state["datasets"][chosen_dataset]), prompt, openai_api_key)
            else:
                answer = ask_gpt("", prompt, openai_api_key)

            if "plt.show()" in answer or "plt" in answer:
                plot_image = execute_and_capture_plot(answer)
                if plot_image:
                    msg = 'A visualization has been created based on your prompt'
                    st.session_state.messages.append({"role": "assistant", "content": msg, "prompt": prompt, "image": plot_image})
                    st.chat_message("assistant").write(msg)
                    st.chat_message("assistant").image(plot_image, caption="Generated Plot", use_column_width=True)
                    st.session_state["vis_code"] = answer
            else:
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.chat_message("assistant").write(answer)

    if chosen_dataset:
        st.subheader(f"{chosen_dataset} Dataset")
        st.dataframe(st.session_state["datasets"][chosen_dataset], hide_index=True)

