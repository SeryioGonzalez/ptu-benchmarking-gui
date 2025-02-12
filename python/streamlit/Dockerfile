FROM python:3.12
WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

ARG STREAMLIT_PORT
ENV STREAMLIT_PORT=${STREAMLIT_PORT}

COPY . /app

EXPOSE ${STREAMLIT_PORT}

CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port=$STREAMLIT_PORT --server.headless=true"]

