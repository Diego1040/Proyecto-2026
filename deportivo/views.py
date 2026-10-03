from django.shortcuts import render

# Create your views here.
def EntrenadorView(request):
    return render(request, 'entrenador.html')