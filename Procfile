# 🆕 For the Damage Analysis Agent service
damage: python -m gunicorn -t 120 agents.damage_analysis_agent.main_handler:app --bind 0.0.0.0:$PORT

# For the Streamlit UI service (reliefx-ui)
web: streamlit run ui/app.py --server.port $PORT --server.address 0.0.0.0

# For the Logistics Agent service (logistics-agent)
logistics: python -m gunicorn -t 120 agents.logistics_agent.main_handler:app --bind 0.0.0.0:$PORT