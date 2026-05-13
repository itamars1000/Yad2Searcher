# test_filters.py
import sys
sys.stdout.reconfigure(encoding='utf-8')
from utils import contains_blocked_keywords, satisfies_neighborhood_filter

print("======== TESTING BLOCKED KEYWORDS ========")

text1 = "דירת 3 חדרים מדהימה להשכרה בפלורנטין. לא קרקע. כניסה במיידי!"
kw_list = "מרתף, קרקע, סאבלט"
print(f"Text: {text1}")
print(f"Keywords: {kw_list}")
is_blocked = contains_blocked_keywords(text1, kw_list)
print(f"Blocked? {is_blocked} (Expected: True because 'קרקע' is in the text)")

print("\n-------------------------------------------")

text2 = "מחפש שותף בדירה במרכז העיר, 3500 דולר. יש מרפסת."
kw_list2 = "סאבלט, ללא חלונות, מרתף"
print(f"Text: {text2}")
print(f"Keywords: {kw_list2}")
is_blocked2 = contains_blocked_keywords(text2, kw_list2)
print(f"Blocked? {is_blocked2} (Expected: False because none of the keywords are in the text)")


print("\n\n======== TESTING NEIGHBORHOODS ========")

text3 = "דירה להשכרה ברחוב בזל פינת אבן גבירול, הצפון הישן. כניסה במיידי!"
nb_list = "פלורנטין, הצפון הישן, לב העיר"
print(f"Text: {text3}")
print(f"User Neighborhoods: {nb_list}")
is_match = satisfies_neighborhood_filter(text3, nb_list)
print(f"Satisfies filter? {is_match} (Expected: True because 'הצפון הישן' is in the text)")

print("\n-------------------------------------------")

text4 = "דירה מטורפת בדרום תל אביב, שכונת שפירא."
nb_list2 = "בבלי, רמת אביב, לוינסקי"
print(f"Text: {text4}")
print(f"User Neighborhoods: {nb_list2}")
is_match2 = satisfies_neighborhood_filter(text4, nb_list2)
print(f"Satisfies filter? {is_match2} (Expected: False because none of the user's neighborhoods are in the text)")

print("\n-------------------------------------------")

text5 = "דירת גן בשכונת פלורנטין."
nb_list3 = ""
print(f"Text: {text5}")
print(f"User Neighborhoods: empty (no specific neighborhood chosen)")
is_match3 = satisfies_neighborhood_filter(text5, nb_list3)
print(f"Satisfies filter? {is_match3} (Expected: True because empty means they want everything)")

