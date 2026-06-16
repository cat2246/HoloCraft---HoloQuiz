from holoquiz.parser import AnswerReveal, QuizQuestion, parse_log_line


def test_parse_holoquiz_question():
    line = "[17:36:04] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft? = ?"

    event = parse_log_line(line)

    assert event == QuizQuestion(question="Who created Minecraft? = ?")


def test_parse_holoquiz_question_without_equals_marker():
    line = "[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] What mob explodes near players?"

    event = parse_log_line(line)

    assert event == QuizQuestion(question="What mob explodes near players?")


def test_parse_holoquiz_question_with_arithmetic_like_text():
    line = "[17:42:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] What item is crafted with 3 sticks?"

    event = parse_log_line(line)

    assert event == QuizQuestion(question="What item is crafted with 3 sticks?")


def test_parse_holoquiz_easter_egg_clue_with_dash_blank():
    line = (
        "[17:45:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] "
        "Easter Egg: Did you know that there are easter eggs within HoloQuiz? "
        "For instance, /Holoquiz -------- was the answer to one of the HoloAnniv challenges!"
    )

    event = parse_log_line(line)

    assert event == QuizQuestion(
        question=(
            "Easter Egg: Did you know that there are easter eggs within HoloQuiz? "
            "For instance, /Holoquiz -------- was the answer to one of the HoloAnniv challenges!"
        )
    )


def test_parse_holoquiz_trivia_clue_with_question_mark_and_dash_blank():
    line = (
        "[17:46:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] "
        "Hololive - Trivia: Contrary to popular belief, IRyS is not an acronym for her full name. "
        "Instead her full name is ??????? ----"
    )

    event = parse_log_line(line)

    assert event == QuizQuestion(
        question=(
            "Hololive - Trivia: Contrary to popular belief, IRyS is not an acronym for her full name. "
            "Instead her full name is ??????? ----"
        )
    )


def test_ignore_non_holoquiz_chat():
    line = "[17:36:16] [Render thread/INFO]: [System] [CHAT] [Newbie] truntd: 42"

    assert parse_log_line(line) is None


def test_ignore_chat_message_that_mentions_holoquiz():
    line = "[17:41:00] [Render thread/INFO]: [System] [CHAT] [Newbie] bob: [HoloQuiz] Who created Minecraft?"

    assert parse_log_line(line) is None


def test_ignore_math_expression_prompt():
    line = "[17:36:04] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?"

    assert parse_log_line(line) is None


def test_ignore_fraction_math_expression_prompt():
    line = "[17:35:29] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] (2+3-0/5)+13 = ?"

    assert parse_log_line(line) is None


def test_parse_answer_reveal():
    line = "[17:35:59] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was 18."

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="18")


def test_parse_answer_reveal_with_negative_answer():
    line = "[17:36:19] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] FedericoAlio214 wins after 14.738 seconds! The answer was -42!"

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="-42")


def test_parse_answer_reveal_strips_repeated_punctuation():
    line = "[17:43:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was Notch!!!"

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="Notch")


def test_parse_answer_reveal_strips_question_mark():
    line = "[17:44:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was Steve?"

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="Steve")
