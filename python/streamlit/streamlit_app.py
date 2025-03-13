import logging
import os
import requests
import streamlit as st
import time

from datetime import datetime, timedelta

GRAFANA_DASHBOARD_UID = "ce977t8gv5czkb/ptu-benchmarking-v2"
GRAFANA_PORT = os.getenv("GRAFANA_PORT")
BENCHMARK_TOOL_API_PORT = os.getenv("BENCHMARK_TOOL_API_PORT")

USE_DEFAULTS = True

DEFAULT_ENDPOINT_LABEL_1 = os.getenv("DEFAULT_ENDPOINT_LABEL_1") or None
DEFAULT_ENDPOINT_URL_1 = os.getenv("DEFAULT_ENDPOINT_URL_1") or None
DEFAULT_ENDPOINT_KEY_1 = os.getenv("DEFAULT_ENDPOINT_KEY_1") or None
DEFAULT_ENDPOINT_DEPLOYMENT_1 = os.getenv("DEFAULT_ENDPOINT_DEPLOYMENT_1") or None

DEFAULT_ENDPOINT_LABEL_2 = os.getenv("DEFAULT_ENDPOINT_LABEL_2") or None
DEFAULT_ENDPOINT_URL_2 = os.getenv("DEFAULT_ENDPOINT_URL_2") or None
DEFAULT_ENDPOINT_KEY_2 = os.getenv("DEFAULT_ENDPOINT_KEY_2") or None
DEFAULT_ENDPOINT_DEPLOYMENT_2 = os.getenv("DEFAULT_ENDPOINT_DEPLOYMENT_2") or None

DEFAULT_PROMPT_TOKENS = int(os.getenv("DEFAULT_PROMPT_TOKENS", 0)) or None
DEFAULT_COMPLETION_TOKENS = int(os.getenv("DEFAULT_COMPLETION_TOKENS", 0)) or None

logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG for more detailed logs
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

def start_benchmarks():
    logger.debug(f"Starting benchmarks - ENDPOINT_1 {st.session_state.endpoint_1_status} - ENDPOINT_2 {st.session_state.endpoint_2_status}")
    if not (st.session_state.endpoint_1_status and st.session_state.endpoint_2_status):
        st.error("Check the configuration of the endpoints before starting the benchmarks.")
        return

    common_attributes = {
        "replay_path": "prompts.json",
        "context_generation_method": "reply",
        "duration": st.session_state.experiment_data['duration'],
        "rate": st.session_state.experiment_data['rpm']
    }

    payload_endpoint_1 = {
        **common_attributes,
        "api_base_endpoint": st.session_state.endpoint_endpoint_1,
        "deployment": st.session_state.deployment_endpoint_1,
        "api_key": st.session_state.api_key_endpoint_1,
        "custom_label": st.session_state.custom_label_endpoint_1
    }

    payload_endpoint_2 = {
        **common_attributes,
        "api_base_endpoint": st.session_state.endpoint_endpoint_2,
        "deployment": st.session_state.deployment_endpoint_2,
        "api_key": st.session_state.api_key_endpoint_2,
        "custom_label": st.session_state.custom_label_endpoint_2
    }
    
    try:
        response_endpoint_1 = requests.post(f"http://benchmark_endpoint_1:{BENCHMARK_TOOL_API_PORT}/load", json=payload_endpoint_1, timeout=60)
        response_endpoint_2 = requests.post(f"http://benchmark_endpoint_2:{BENCHMARK_TOOL_API_PORT}/load", json=payload_endpoint_2, timeout=60)

        success_placeholder = st.empty()
        info_placeholder = st.empty()

        if response_endpoint_1.ok and response_endpoint_2.ok:
            start_time = datetime.now()
            formatted_start = start_time.strftime("%H:%M:%S")
            end_time = start_time + timedelta(seconds=st.session_state.experiment_data['duration'])
            formatted_end = end_time.strftime("%H:%M:%S")

            success_placeholder.success(f"Benchmarks started successfully at {formatted_start}")
            info_placeholder.info(f"Benchmarks will end at {formatted_end}")
        else:
            error_messages = f"Benchmark 1 Error: {response_endpoint_1.text if not response_endpoint_1.ok else 'OK'}\n" \
                             f"Benchmark 2 Error: {response_endpoint_2.text if not response_endpoint_2.ok else 'OK'}"
            info_placeholder.error(f"Error in launching benchmarks:\n{error_messages}")
            return {"error": error_messages}

    except requests.exceptions.RequestException as e:
        info_placeholder.error(f"Error launching test: {e}")
        return {"error": str(e)}

def display_endpoint_status(label, status, col):
    """Display a configuration item with a green or red indicator, centered in the column."""
    color = "green" if status else "red"
    col.markdown(
        f"""
        <div style='display: flex; align-items: center; justify-content: center; margin: 10px 0;'>
            <div style='width: 12px; height: 12px; border-radius: 50%; background-color: {color}; margin-right: 10px;'></div>
            <span>{label}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

def check_az_openai_endpoint_status(api_key, endpoint, deployment):
    # Validate api_key
    if not api_key:
        return False

    # Validate endpoint URL
    if not endpoint:
        return False
    if not endpoint.startswith("https://"):
        return False
    
    # Validate deployment name
    if not deployment:
        print("Validation failed: The deployment name is missing or empty.")
        return False
    
    # Construct the URL
    try:
        url = (endpoint
                + "/openai/deployments/"
                + deployment
                + "/chat/completions"
                + "?api-version=2024-05-01-preview"
            )
    except Exception as e:
        print(f"Validation failed: Error constructing the URL: {e}")
        return False
    
    # Headers and body
    model_check_headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }
    model_check_body = {"messages": [{"content": "What is 1+1?", "role": "user"}]}
    
    # Validate endpoint response
    try:
        response = requests.post(url, headers=model_check_headers, json=model_check_body, timeout=10)
        if response.status_code == 200:
            return True
        else:
            # Log detailed response for debugging
            print(f"Validation failed: {response.status_code}, {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Validation failed: Failed to reach the endpoint. Error: {e}")
        return False

if "api_key_endpoint_1" not in st.session_state:
    st.session_state.api_key_endpoint_1 = ""
    st.session_state.endpoint_endpoint_1 = ""
    st.session_state.deployment_endpoint_1 = ""
    st.session_state.endpoint_1_status = False

    st.session_state.api_key_endpoint_2 = ""
    st.session_state.endpoint_endpoint_2 = ""
    st.session_state.deployment_endpoint_2 = ""
    st.session_state.endpoint_2_status = False

    st.session_state.experiment_data = {}
    st.session_state.experiment_data['active_experiment'] = False
    st.session_state.experiment_data["context_generation_method"] = "generate"
    st.session_state.experiment_data["shape_profile"] = "custom"

st.set_page_config(layout="wide")

st.title("Az OpenAI Benchmarking")

# 1) Collect configuration inputs
with st.sidebar:
    st.header("Azure OpenAI endpoint settings")

    with st.expander("Endpoint 1"):
        st.session_state.custom_label_endpoint_1 = st.text_input("Endpoint label 1", value=DEFAULT_ENDPOINT_LABEL_1)
        st.session_state.api_key_endpoint_1 = st.text_input("AzOpenAI API Key 1", type="password", value=DEFAULT_ENDPOINT_KEY_1 if USE_DEFAULTS else None)
        st.session_state.endpoint_endpoint_1 = st.text_input("AzOpenAI Endpoint 1", value=DEFAULT_ENDPOINT_URL_1 if USE_DEFAULTS else None)
        st.session_state.deployment_endpoint_1 = st.text_input("AzOpenAI Model Deployment 1", value=DEFAULT_ENDPOINT_DEPLOYMENT_1 if USE_DEFAULTS else None)
    
    with st.expander('Endpoint 2'):
        st.session_state.custom_label_endpoint_2 = st.text_input("Endpoint label 2", value=DEFAULT_ENDPOINT_LABEL_2)
        st.session_state.api_key_endpoint_2 = st.text_input("AzOpenAI API Key 2", type="password", value=DEFAULT_ENDPOINT_KEY_2 if USE_DEFAULTS else None)
        st.session_state.endpoint_endpoint_2 = st.text_input("AzOpenAI Endpoint 2", value=DEFAULT_ENDPOINT_URL_2 if USE_DEFAULTS else None)
        st.session_state.deployment_endpoint_2 = st.text_input("AzOpenAI Model Deployment 2", value=DEFAULT_ENDPOINT_DEPLOYMENT_2 if USE_DEFAULTS else None)

    col1, col2 = st.columns(2)

    st.session_state.endpoint_1_status   = check_az_openai_endpoint_status(st.session_state.api_key_endpoint_1,   st.session_state.endpoint_endpoint_1,   st.session_state.deployment_endpoint_1)
    st.session_state.endpoint_2_status = check_az_openai_endpoint_status(st.session_state.api_key_endpoint_2, st.session_state.endpoint_endpoint_2, st.session_state.deployment_endpoint_2)

    display_endpoint_status("Endpoint 1",   st.session_state.endpoint_1_status, col1)
    display_endpoint_status("Endpoint 2", st.session_state.endpoint_2_status, col2)

    st.header("Benchmark configuration")
    with st.expander('Config'):
        st.session_state.experiment_data['duration'] = st.number_input("Experiment Duration (seconds)", min_value=30, value=30)
        st.session_state.experiment_data['rpm']      = st.number_input("Requests per minute (0 is no limit)", min_value=0, max_value=100000, value=0)
        
        st.session_state.experiment_data['context_tokens'] = st.number_input("Prompt tokens per request", min_value=30, value=DEFAULT_PROMPT_TOKENS)
        st.session_state.experiment_data['max_tokens'] = st.number_input("Completion tokens per request", min_value=30, value=DEFAULT_COMPLETION_TOKENS)

    if st.button("Run Benchmark"):
        if st.session_state.endpoint_1_status and st.session_state.endpoint_2_status:
            st.session_state.experiment_data['active_experiment'] = True
            st.session_state.experiment_data['start_time'] = datetime.now()
            st.session_state.experiment_data['end_time'] = st.session_state.experiment_data['start_time'] + timedelta(seconds=st.session_state.experiment_data['duration'])

            start_benchmarks()
        else:
            st.warning("Please check the endpoint configuration before starting the benchmarks.")


st.write("## Live Dashboard")

clock_placeholder = st.empty()

dashboard_url = f"http://localhost:{GRAFANA_PORT}/d/{GRAFANA_DASHBOARD_UID}?orgId=1&kiosk"

logger.info(f"Dashboard in {dashboard_url}")
# If your dashboard is anonymous, this iframe should just work:
st.components.v1.iframe(dashboard_url, width=1400, height=900)

while True:
    # Update the clock every second
    # Get the current time and format it
    time_now = datetime.now()
    time_now_formatted = time_now.strftime("%H:%M:%S")

    display_message = f"### Current time: {time_now_formatted}. "

    # 

    if st.session_state.experiment_data['active_experiment']:
        # Check if the experiment is still active
        if datetime.now() >= st.session_state.experiment_data['end_time']:
            st.session_state.experiment_data['active_experiment'] = False
            st.session_state.experiment_data['start_time'] = None
            st.session_state.experiment_data['end_time'] = None
            display_message += "Benchmark completed successfully!"
            
        else:
            time_remaining = st.session_state.experiment_data['end_time'] - datetime.now()
            time_remaining_formatted = str(time_remaining).split(".")[0]

            display_message += f"Time remaining for current benchmark: {time_remaining_formatted}"

    clock_placeholder.markdown(display_message)
    time.sleep(1)