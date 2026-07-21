from django import forms
from .models import  CustomUser, Profile
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm


class UserRegisterForm(forms.ModelForm):
    email = forms.EmailField(widget=forms.TextInput(attrs={'class':'form-controls' }))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-controls' }))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-controls' }))
    
    class Meta:
        model  = CustomUser
        fields = ['email']

        
class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()
    class Meta:
        model  = CustomUser
        fields = ['email']
        
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'first_name', 'surname', 'date_of_birth', 'phone',
            'profile_picture', 'cultural_background', 'religious_affiliation',
            'traditional_names', 'spiritual_beliefs', 'bio'
        ]
        
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'First Name',
                'style': 'width: 90%;'
                'hover: focus:border-blue-500'
                
            }),
            'surname': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'Surname',
                'style': 'width: 90%;'
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 datepicker-input',
                'type': 'text',
                'placeholder': 'YYYY-MM-DD',
                'style': 'width: 90%;'
            }),
            'bio': forms.Textarea(attrs={
                'class': 'w-full  border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'rows': 4,
                'placeholder': 'Tell us about yourself...'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g. +27123456789',
                'style': 'width: 90%;'
            }),
            'cultural_background': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g. Zulu, Xhosa, Afrikaans',
                'style': 'width: 90%;'
            }),
            'religious_affiliation': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g. Christianity, Islam',
                'style': 'width: 90%;'
            }),
            'traditional_names': forms.TextInput(attrs={
                'class': 'form-control border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g. Clan or family names',
                'style': 'width: 90%;'
            }),
            'spiritual_beliefs': forms.Textarea(attrs={
                'class': 'w-full  border border-gray-600 text-gray-500 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'rows': 4,
                'placeholder': 'e.g. Animism, Ancestor worship'
            }),
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'form-control'
            }),
        }

        
        
class CustomSignupForm(forms.Form):
    email = forms.EmailField(label="Email", max_length=254, required=True, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Password", required=True, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm Password", required=True, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError({"password2": "Passwords do not match."})
        return cleaned_data        


        
        


