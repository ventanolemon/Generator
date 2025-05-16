from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
@app.route("/index")
def index():
    params = {
        "host": host,
        "port": port
    }
    return render_template("index.html", **params)


if __name__ == "__main__":
    port = 8080
    host = "localhost"  #127.0.0.1
    app.run(host=host, port=port)
