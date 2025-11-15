from app import app, db, SuperAdmin
from werkzeug.security import generate_password_hash

TARGET_NAME = 'Digital Homeez'
TARGET_USERNAME = 'digihomeez'
TARGET_PASSWORD = 'digisid@5500'


def main():
    with app.app_context():
        existing = SuperAdmin.query.filter_by(username=TARGET_USERNAME).first()
        if existing:
            print(f"Super Admin '{TARGET_USERNAME}' already exists (id={existing.id}). Nothing to do.")
            return
        sa = SuperAdmin(
            name=TARGET_NAME,
            username=TARGET_USERNAME,
            password_hash=generate_password_hash(TARGET_PASSWORD)
        )
        db.session.add(sa)
        db.session.commit()
        print(f"Super Admin created: {sa.name} ({sa.username}), id={sa.id}")


if __name__ == '__main__':
    main()
