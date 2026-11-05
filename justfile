# Pull main, then test, migrate and deploy the Worker.
deploy:
    pixi run deploy

# Pull main, test, then deploy the server to FastAPI Cloud.
deploy-cloud:
    pixi run deploy-cloud
