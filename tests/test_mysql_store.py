import unittest


class MySQLStoreTests(unittest.TestCase):
    def test_open_connection_uses_db_context_manager_directly(self):
        from memoryendpoints.storage import MySQLStore

        class FakeConnection(object):
            pass

        class FakeMySQLStore(MySQLStore):
            def __init__(self):
                pass

            def _connect(self):
                return self.fake_connection

        store = FakeMySQLStore()
        store.fake_connection = FakeConnection()

        self.assertIs(store.fake_connection, store._open_connection())


if __name__ == "__main__":
    unittest.main()
