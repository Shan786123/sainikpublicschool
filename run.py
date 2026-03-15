import os
from app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n{'='*50}")
    print(f"  Sainik Public School — Server Starting")
    print(f"  URL: http://localhost:{port}")
    print(f"  Admin: http://localhost:{port}/admin/login")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=port, debug=False)