FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY directory_site/ directory_site/
COPY README.md .

# members.json 없으면 빈 배열로 초기화
RUN echo '[]' > members.json

ENV PORT=7860
EXPOSE 7860

CMD ["python", "server.py"]