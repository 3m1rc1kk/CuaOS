
from transformers import MarianMTModel, MarianTokenizer

model_name = "Helsinki-NLP/opus-mt-tc-big-tr-en"
tokenizer = MarianTokenizer.from_pretrained(model_name)
model = MarianMTModel.from_pretrained(model_name)



objective = "merhaba!"

translated = model.generate(**tokenizer(objective, return_tensors="pt", padding=True))
for t in translated:
    print( tokenizer.decode(t, skip_special_tokens=True) )
ceviri=tokenizer.decode(t, skip_special_tokens=True)


print(ceviri)