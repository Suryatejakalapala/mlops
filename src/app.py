# src/app.py
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "The ML service is running"})

@app.route('/predict', methods=['POST'])
def predict():
    # This is a placeholder for your future ML prediction endpoint
    data = request.get_json()
    
    # In a real application, you would:
    # 1. Load your trained model
    # 2. Preprocess the input data
    # 3. Make predictions
    # 4. Return the results
    
    return jsonify({
        "prediction": "placeholder",
        "model_version": "0.1.0",
        "received_data": data
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)