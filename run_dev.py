from wsgiref.simple_server import make_server

from app import application


def main():
    host = "127.0.0.1"
    port = 8088
    print("MemoryEndpoints dev server: http://%s:%s" % (host, port))
    server = make_server(host, port, application)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
