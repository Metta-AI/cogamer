"""AWS Lambda handler — wraps the FastAPI app with Mangum."""

from mangum import Mangum

from cogamer.api.app import app

handler = Mangum(app, lifespan="off")
