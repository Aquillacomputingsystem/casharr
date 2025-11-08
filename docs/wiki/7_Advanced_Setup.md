<p align="left">
  <img src="./assets/casharr_logo_white.png" alt="Casharr Logo" width="150"/>
</p>

# ⚡ Advanced Setup

### Docker Deployment
Use a Dockerfile to containerize Casharr. Example:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
```



