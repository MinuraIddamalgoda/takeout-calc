from django.shortcuts import render
from django.http import HttpResponse


def home(request):
    return HttpResponse("This is our homepage")


def orders(request):
    return HttpResponse("This is our orders page")
