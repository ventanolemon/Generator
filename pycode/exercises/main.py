import requests


data = {
    'email': 'admin@mail.ru',
    'name': 'Admin',
    'password': 'admin'
}
print(requests.post('http://127.0.0.1:8080/users/', json=data).json())

print(requests.get("http://127.0.0.1:8080/").content)
print(requests.get("http://127.0.0.1:8080/users").json())
print(requests.get("http://127.0.0.1:8080/users/1").json())
print(requests.get("http://127.0.0.1:8080/users/dwadaw/dawdawdaw/").content)

data = {
    'email': 'admin@mail.ru',
    'password': 'admin'
}
response = requests.post('http://127.0.0.1:8080/users_auth/', json=data).json()
if 'user' in response and response['user']:
    user = response['user']
    print(user['id'])
    data = {
        'password': 'admin1'
    }
    print(requests.put(f'http://127.0.0.1:8080/users/{user['id']}', json=data).json())


    print(requests.delete(f'http://127.0.0.1:8080/users/{user['id']}'))
print(requests.delete(f'http://127.0.0.1:8080/users').json())