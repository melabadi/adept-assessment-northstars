# The image of the release jobs (infra/jobs.bicep): release.py and its settings helper on Python, nothing else.
# azd builds it in Azure Container Registry (`azd deploy release`); the jobs pull it with their managed identity.
FROM mcr.microsoft.com/azurelinux/base/python:3.12
WORKDIR /release
COPY azd_env.py release.py ./
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "release.py"]
