import os
from app import app, init_db

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
    print(f"\n{'='*50}")
    print(f"  Sainik Public School — Server Starting")
    print(f"  URL: http://localhost:{port}")
    print(f"  Admin: http://localhost:{port}/admin/login")
    print(f"  Admin login: admin / admin123")
    print(f"  Student login: STU001 / password123")
    print(f"{'='*50}\n")
    app.run(host=host, port=port, debug=False)
