import sys
import time
from PyQt6 import QtWidgets, QtCore, uic
import random


class LastWords:
    def __init__(self):
        self.last_words = []

    def append(self, __object):
        self.last_words.append(__object)
        if len(self.last_words) > 10:
            self.last_words = self.last_words[-10:]

    def __contains__(self, item):
        return item in self.last_words

    def __str__(self):
        return ' '.join(self.last_words)


def choose(sp, last):
    new = random.choice(sp)
    if new not in last:
        last.append(new)
        return new, last
    else:
        return choose(sp, last)


s = ['Прибаутка', 'Беспрекословный', 'Приберечь', 'Не преминуть', 'Приватизация', 'Непрестанный', 'Привередливый,', 'привереда', 'Преамбула', 'Приверженец', 'Превалировать', 'Привидение', 'Презентация,', 'презентабельный', 'Привилегия', 'Президент,', 'президиум', 'Придирчивый', 'Презумпция', 'Приемлемый', 'Прельститься', 'Прижимистый', 'Прелюдия', 'Призвание', 'Пренебрежение,', 'пренебрегать', 'Приключение', 'Препарировать', 'Прилежный', '(Знаки) препинания', 'Примадонна', 'Препона', 'Примечание', 'Препроводить', 'Примитивный', 'Пререкаться', 'Приоритет', 'Прерогатива', 'Прискорбный,', 'прискорбие', 'Пресечь', 'Пристрастный,', 'пристрастие', 'Преследовать', 'Присягать', 'Пресловутый', 'Притворство,', 'притворщик', 'Пресмыкающийся', 'Причитать', 'Престиж', 'Причудливый,', 'причуда', 'Престол,', 'престольный', 'Неприступный', 'Претендент', 'Неприхотливый', 'Претензия', 'Прецедент', 'Преферанс']
s_n = ['Пр_баутка', 'Беспр_кословный', 'Пр_беречь', 'Не пр_минуть', 'Пр_ватизация', 'Непр_станный', 'Пр_вередливый,', 'пр_вереда', 'Пр_амбула', 'Пр_верженец', 'Пр_валировать', 'Пр_видение', 'Пр_зентация,', 'пр_зентабельный', 'Пр_вилегия', 'Пр_зидент,', 'пр_зидиум', 'Пр_дирчивый', 'Пр_зумпция', 'Пр_емлемый', 'Пр_льститься', 'Пр_жимистый', 'Пр_людия', 'Пр_звание', 'Пр_небрежение,', 'пр_небрегать', 'Пр_ключение', 'Пр_парировать', 'Пр_лежный', '(Знаки) пр_пинания', 'Пр_мадонна', 'Пр_пона', 'Пр_мечание', 'Пр_проводить', 'Пр_митивный', 'Пр_рекаться', 'Пр_оритет', 'Пр_рогатива', 'Пр_скорбный,', 'пр_скорбие', 'Пр_сечь', 'Пр_страстный,', 'пр_страстие', 'Пр_следовать', 'Пр_сягать', 'Пр_словутый', 'Пр_творство,', 'пр_творщик', 'Пр_смыкающийся', 'Пр_читать', 'Пр_стиж', 'Пр_чудливый,', 'пр_чуда', 'Пр_стол,', 'пр_стольный', 'Непр_ступный', 'Пр_тендент', 'Непр_хотливый', 'Пр_тензия', 'Пр_цедент', 'Пр_феранс']
data = tuple(zip(s, s_n))
class MainGame(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi('russGame.ui', self)
        self.cnt, self.lcnt = 0, 0
        self.loose_words = []
        self.last = LastWords()
        self.make()
        self.started = False
        self.curWord = ()

    def make(self):
        self.progressBar.setValue(0)
        self.winFrame.hide()
        self.startButton.clicked.connect(self.game)
        self.stopButton.clicked.connect(self.stop)

    def game(self):
        self.startButton.hide()
        self.winFrame.hide()
        self.started = True
        self.inputLetter.setText('_')
        k = choose(data, self.last)
        self.word, self.last = k
        right, task = self.word
        self.currentWord.setText(task)
        self.inputLetter.setStyleSheet('')

    def stop(self):
        try:
            self.started = False
            self.winFrame.show()

            self.txtCnt.setText(f'{self.cnt}/{self.cnt + self.lcnt}')
            res_data = QtCore.QStringListModel(map(lambda i: i[0], self.loose_words))
            self.FalsListView.setModel(res_data)
            self.progressBar.setValue(0)
            self.startButton.show()
            self.cntLoose.display(0)
            self.cntRight.display(0)
            self.status.setText('_')
        except Exception as ex:
            print(ex)

    def keyPressEvent(self, a0):
        try:
            right, task = self.word
            symbol = a0.text()
            if (not symbol.rstrip()) or (symbol not in 'ие' or not self.started):
                raise Exception
            self.inputLetter.setText(symbol)
            if task.replace('_', symbol) == right:
                self.cnt += 1
                self.cntRight.display(self.cnt)
                self.status.setText('Правильно!')
                self.inputLetter.setStyleSheet('background : green')
                # print('great!', self.cnt, self.lcnt)
            else:
                self.lcnt += 1
                # print('loose', right)
                self.loose_words.append(self.word)
                self.cntLoose.display(self.lcnt)
                self.status.setText('Ошибка(')
                self.inputLetter.setStyleSheet('background : red')
            self.progressBar.setValue(self.progressBar.value() + 1)
            time.sleep(0.25)
            self.game()
        except Exception as ex:
            print(ex)
# print(cnt)
# print(loose_words)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    game = MainGame()
    game.show()
    sys.exit(app.exec())
