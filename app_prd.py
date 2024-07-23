import streamlit as st
import pandas as pd
import sqlite3
import io
import matplotlib.pyplot as plt
import stripe
from helpers import *

# Load Stripe secret key
stripe_secret_key = st.secrets["stripe_secret_key"]
stripe.api_key = stripe_secret_key

# Initialize SQLite database
conn = sqlite3.connect('users.db')
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        email TEXT PRIMARY KEY,
        password TEXT NOT NULL
    )
''')
conn.commit()

def add_user(email, password):
    try:
        c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, password))
        conn.commit()
    except sqlite3.IntegrityError:
        st.error("User already exists. Please sign in.")

def authenticate_user(email, password):
    c.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password))
    return c.fetchone()

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
            success_url='https://datatovischatbot.streamlit.app?payment=success',
            cancel_url='https://datatovischatbot.streamlit.app?payment=cancel',
        )
        return session.url
    except Exception as e:
        st.error(f"Error creating checkout session: {e}")
        return None

# Initialize in-memory session state
if "auth_status" not in st.session_state:
    st.session_state["auth_status"] = False
if "user_email" not in st.session_state:
    st.session_state["user_email"] = ""
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]
if "vis_code" not in st.session_state:
    st.session_state["vis_code"] = ""

def sign_up(email, password):
    add_user(email, password)
    st.success("Sign Up Successful. Please Sign In.")

def sign_in(email, password):
    user = authenticate_user(email, password)
    if user:
        st.session_state["auth_status"] = True
        st.session_state["user_email"] = email
        st.success("Sign In Successful.")
        return True
    else:
        st.error("Invalid email or password.")
        return False

def sign_out():
    st.session_state["auth_status"] = False
    st.session_state["user_email"] = ""
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]
    st.session_state["vis_code"] = ""
    if "datasets" in st.session_state:
        del st.session_state["datasets"]

# Load user-uploaded dataset
def load_user_dataset(uploaded_file):
    if uploaded_file is not None:
        return pd.read_csv(uploaded_file)
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
        
# Authentication
if not st.session_state["auth_status"]:
    auth_mode = st.sidebar.radio("Authentication", ["Sign Up", "Sign In"])

    if auth_mode == "Sign Up":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Sign Up"):
            sign_up(email, password)
    elif auth_mode == "Sign In":
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        if st.sidebar.button("Sign In"):
            if sign_in(email, password):
                st.experimental_rerun()
else:
    st.sidebar.write(f"Signed in as {st.session_state['user_email']}")
    if st.sidebar.button("Sign Out"):
        sign_out()
        st.experimental_rerun()

    with st.sidebar:
        openai_api_key = st.text_input("Please Input OpenAI API Key below:", key="chatbot_api_key", type="password")

    if st.session_state["auth_status"]:
        payment_url = create_checkout_session()
        if payment_url:
            st.markdown(f'<a href="{payment_url}" target="_blank"><button style="background-color:green">Buy me a Coffee</button></a>', unsafe_allow_html=True)

    st.title("💬 Data to Visualization Chatbot")
    st.caption("An interactive chatbot designed to conduct data analysis and create data visualizations from natural language")

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])
        if "image" in msg:
            st.chat_message("assistant").image(msg["image"], caption=msg["prompt"], use_column_width=True)

    st.markdown("---")
    st.markdown("### Prompt Guide")
    st.markdown("- 🗒️ Start with \"Explore:\" to get suggested prompt from ChatGPT")
    st.markdown("- 📉 Start with \"Show:\" to have ChatGPT generate a plot based on your entered prompt")
    st.markdown("- 📖 Say \"Describe it\" to have ChatGPT describe the plot it just generated for you")

    uploaded_file = st.file_uploader("Upload your dataset (CSV)", type=["csv"])

    if uploaded_file:
        user_dataset = load_user_dataset(uploaded_file)
        if user_dataset is not None:
            st.session_state["datasets"] = {"User Data": user_dataset}
            chosen_dataset = "User Data"
        else:
            st.error("Failed to load dataset.")
    else:
        st.info("Please upload a CSV file to proceed.")

    if "datasets" in st.session_state and st.session_state["datasets"]:
        chosen_dataset = "User Data"

        if prompt := st.chat_input():
            if not openai_api_key:
                st.error("Please add your OpenAI API key to continue.")
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
