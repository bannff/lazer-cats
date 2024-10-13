import sqlite3

def checkName():
    name = input("What is your name?\n")

    # connect to the database
    db = sqlite3.connect('example.db')
    cursor = db.cursor()

    # query all user IDs where firstname matches the user's input
    cursor.execute("SELECT id FROM users WHERE firstname = ?", (name,))

    # fetch the first result of the query above
    result = cursor.fetchone()

    # if the result is not empty, we've found a match
    if result and len(result) > 0:
        print("Hello,", name, ", your user ID is", result[0])

    # otherwise, we haven’t found this user by name
    else:
        print("We couldn't find your user ID in the system,", name)

    db.close()


checkName()