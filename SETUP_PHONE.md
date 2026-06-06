services:
  - type: web
    name: endurance-coach-pwa
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn web.app:app --bind 0.0.0.0:$PORT
    envVars:
      - key: DRY_RUN
        value: "true"
      - key: ATHLETE_NAME
        value: Osho
      - key: SEX
        value: male
      - key: AGE
        value: "35"
      - key: HEIGHT_CM
        value: "180"
      - key: WEIGHT_KG
        value: "75"
      - key: GOAL
        value: performance
