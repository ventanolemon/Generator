import csv


class MainMenu:
    def __init__(self, auf, reg, start):
        self.auf = auf
        self.reg = reg
        self.start = start

        self.commands = {1: self.registration, 2: self.autentification}

        self.cur_obj = self

    def vod(self, command):
        if self.cur_obj.commands.get(command):
            self.cur_obj.commands.get(command)()

    def show(self):
        print("Выберите опцию из меню:")
        print("1) Регистрация")
        print("2) Авторизация")
        return None

    def registration(self):
        self.reg.change_cur_obj(self)
        self.cur_obj = self.reg

    def autentification(self):
        self.auf.change_cur_obj(self)
        self.cur_obj = self.auf

    def change_cur_obj(self, new_obj):
        self.cur_obj = new_obj

    def __str__(self):
        return "главное меню"

    def __repr__(self):
        return "главное меню"


class Auf:
    def __init__(self):
        self.commands = {1: self.go_main_menu, 2: self.autentificat, 3: self.enter_login, 4: self.enter_password}
        self.cur_obj = self

    def change_cur_obj(self, new_obj):
        self.cur_obj = new_obj

    def show(self):
        print("Выберите опцию из меню:")
        print("1) Вернуться в главнок меню")
        print("2) Авторизироваться")
        print("3) Ввести логин")
        print("4) Ввести пароль")
        return None

    def go_main_menu(self):
        self.cur_obj.change_cur_obj(self.cur_obj)

    def autentificat(self):
        with open("database.csv", "r") as file:
            file = csv.reader(file)
            for strok in file:
                print(strok)
                log, pas = strok
                if self.login == log and self.password == pas:
                    self.cur_obj.change_cur_obj(self.cur_obj.start)
                    self.cur_obj.start.change_cur_obj(self.cur_obj)
                    return True
            else:
                return False

    def enter_password(self):
        password = input()
        self.password = password

    def enter_login(self):
        login = input()
        self.login = login

    def __str__(self):
        return "меню аутентификации"

    def __repr__(self):
        return "меню аутентификации"


class Reg:
    def __init__(self):
        self.commands = {1: self.go_main_menu, 2: self.registrate, 3: self.enter_login, 4: self.enter_password}
        self.password = None
        self.login = None
        self.cur_obj = self

    def change_cur_obj(self, new_obj):
        self.cur_obj = new_obj

    def show(self):
        print("Выберите опцию из меню:")
        print("1) Вернуться в главнок меню")
        print("2) Зарегестрироваться")
        print("3) Ввести логин")
        print("4) Ввести пароль")
        return None

    def go_main_menu(self):
        self.cur_obj.change_cur_obj(self.cur_obj)

    def registrate(self):
        self.cur_obj.change_cur_obj(self.cur_obj.start)
        self.cur_obj.start.change_cur_obj(self.cur_obj)
        with open("database.csv", "a") as file:
            file = csv.writer(file)
            file.writerow([self.login, self.password])

    def enter_password(self):
        password = input()
        if len(password) > 6:
            self.password = password
        else:
            print("Длина пароля должна быть больше 6")

    def enter_login(self):
        login = input()
        self.login = login


    def __str__(self):
        return "меню регистрации"

    def __repr__(self):
        return "меню регистрации"


class Start:
    def __init__(self):
        self.commands = {1: self.go_main_menu, 2: self.do_smth}
        self.cur_obj = self

    def change_cur_obj(self, new_obj):
        self.cur_obj = new_obj

    def show(self):
        print("Выберите опцию из меню:")
        print("1) Вернуться в главнок меню")
        print("2) что-то сделать")
        return None

    def go_main_menu(self):
        self.cur_obj.change_cur_obj(self.cur_obj)

    def do_smth(self):
        pass

    def __str__(self):
        return "меню после идентификации"

    def __repr__(self):
        return "меню после идентификации"


if __name__ == "__main__":
    autenf = Auf()
    registr = Reg()
    st = Start()
    menu = MainMenu(autenf, registr, st)
    while True:
        menu.cur_obj.show()
        com = input()
        menu.vod(int(com))
