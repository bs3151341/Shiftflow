import unittest
from unittest.mock import patch

from app import app, db, User, Shift


class PrivateAccessTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app = app
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            manager = User(
                name='Manager User',
                email='manager@test.com',
                password_hash='hashed123',
                role='manager',
                position='Owner'
            )
            db.session.add(manager)
            db.session.commit()

    def test_guest_cannot_open_public_registration(self):
        response = self.app.test_client().get('/register', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_manager_can_create_user_account(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'manager'
            session['name'] = 'Manager User'

        response = client.post(
            '/register',
            data={
                'name': 'New Worker',
                'email': 'worker@test.com',
                'password': 'secret123',
                'role': 'worker',
                'position': 'Crew Member'
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))
        with self.app.app_context():
            user = User.query.filter_by(email='worker@test.com').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role, 'worker')

    def test_secure_cookie_settings_are_enabled(self):
        self.assertTrue(self.app.config.get('SESSION_COOKIE_HTTPONLY'))
        self.assertEqual(self.app.config.get('SESSION_COOKIE_SAMESITE'), 'Lax')

    def test_mobile_wrapper_assets_are_available(self):
        client = self.app.test_client()

        with client.get('/static/manifest.webmanifest') as manifest:
            self.assertEqual(manifest.status_code, 200)
            self.assertIn(b'"display": "standalone"', manifest.data)

        with client.get('/service-worker.js') as service_worker:
            self.assertEqual(service_worker.status_code, 200)
            self.assertIn(b'APP_SHELL', service_worker.data)

    def test_worker_can_accept_assigned_shift(self):
        with self.app.app_context():
            worker = User(
                name='Worker User',
                email='worker@test.com',
                password_hash='hashed456',
                role='worker',
                position='Crew Member'
            )
            db.session.add(worker)
            db.session.commit()
            shift = Shift(
                date='2026-09-28',
                start='09:00',
                end='17:00',
                position='Crew Member',
                manager_id=1,
                worker_id=worker.id,
                decision='Pending'
            )
            db.session.add(shift)
            db.session.commit()
            shift_id = shift.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 2
            session['role'] = 'worker'
            session['name'] = 'Worker User'

        with patch('app.send_email') as send_email:
            response = client.post(f'/shifts/{shift_id}/accept', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        with self.app.app_context():
            updated = Shift.query.get(shift_id)
            self.assertEqual(updated.decision, 'Accepted')

    def test_assigning_shift_sends_worker_email(self):
        with self.app.app_context():
            worker = User(
                name='Worker User',
                email='worker@test.com',
                password_hash='hashed456',
                role='worker',
                position='Crew Member'
            )
            db.session.add(worker)
            db.session.commit()
            worker_id = worker.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'manager'
            session['name'] = 'Manager User'

        with patch('app.send_email') as send_email:
            response = client.post(
                '/shifts/create',
                data={
                    'date': '2026-09-28',
                    'start': '09:00',
                    'end': '17:00',
                    'position': 'Crew Member',
                    'worker_id': str(worker_id),
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        self.assertEqual(send_email.call_args.args[0], 'worker@test.com')

    def test_decline_requires_reason(self):
        with self.app.app_context():
            worker = User(
                name='Worker User',
                email='worker@test.com',
                password_hash='hashed456',
                role='worker',
                position='Crew Member'
            )
            db.session.add(worker)
            db.session.commit()
            shift = Shift(
                date='2026-09-28',
                start='09:00',
                end='17:00',
                position='Crew Member',
                manager_id=1,
                worker_id=worker.id,
                decision='Pending'
            )
            db.session.add(shift)
            db.session.commit()
            shift_id = shift.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 2
            session['role'] = 'worker'
            session['name'] = 'Worker User'

        response = client.post(f'/shifts/{shift_id}/decline', data={'reason': ''}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            updated = Shift.query.get(shift_id)
            self.assertEqual(updated.decision, 'Pending')

    def test_declining_shift_sends_manager_email(self):
        with self.app.app_context():
            worker = User(
                name='Worker User',
                email='worker@test.com',
                password_hash='hashed456',
                role='worker',
                position='Crew Member'
            )
            db.session.add(worker)
            db.session.commit()
            shift = Shift(
                date='2026-09-28',
                start='09:00',
                end='17:00',
                position='Crew Member',
                manager_id=1,
                worker_id=worker.id,
                decision='Pending'
            )
            db.session.add(shift)
            db.session.commit()
            shift_id = shift.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 2
            session['role'] = 'worker'
            session['name'] = 'Worker User'

        with patch('app.send_email') as send_email:
            response = client.post(
                f'/shifts/{shift_id}/decline',
                data={'reason': 'I have another commitment'},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        self.assertEqual(send_email.call_args.args[0], 'manager@test.com')
        self.assertIn('I have another commitment', send_email.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
