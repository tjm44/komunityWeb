from django import forms
from .models import *
import os
from django.contrib.auth.models import User
from PIL import Image
from django.conf import settings
from user.models import Profile


# forms.py

from django import forms
from .models import Profile, GroupMembership

class AddMemberForm(forms.Form):
    """
    Form used to add a new member to a group.
    Ensures:
      - group is passed correctly
      - queryset excludes existing members
      - widget is styled
    """
    member = forms.ModelChoiceField(
        queryset=Profile.objects.none(),
        label="Select New Member",
        required=True,
        widget=forms.Select(
            attrs={
                "class": "w-full px-4 py-3 border border-gray-300 rounded-xl "
                         "focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        group = kwargs.pop("group", None)
        super().__init__(*args, **kwargs)

        # Defensive default
        qs = Profile.objects.all()

        if group:
            existing_ids = GroupMembership.objects.filter(
                group=group
            ).values_list("member_id", flat=True)

            # Exclude already-added members
            qs = qs.exclude(id__in=existing_ids)

        self.fields["member"].queryset = qs



class GroupJoinForm(forms.Form):
    group = forms.ModelChoiceField(queryset=Group.objects.all(),label='Select Group', empty_label='Select a Member')
    

class GroupCreationForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'description', 'cover_image', 'max_members', 'requires_approval', 'is_active']
        
        widgets = {
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 4,
                'placeholder': 'Describe your group...'
            }),
            'cover_image': forms.FileInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'accept': 'image/*'
            }),
            'max_members': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Leave blank for unlimited',
                'min': '1'
            }),
            'requires_approval': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
            })
        }
        
    def __init__(self, *args, **kwargs):
        super(GroupCreationForm, self).__init__(*args, **kwargs)
        self.fields['max_members'].required = False
        self.fields['cover_image'].required = False
    
    
class PostCreationForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['content', 'image', 'video']
        widgets={
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
            }),
        }
        
        

class EditPostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
            }),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets={
            'content': forms.Textarea(attrs={
                'class': 'form-control form-control-md',
                'rows': 4,
            }),
        } 

class CommentEditForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets={
            'content': forms.Textarea(attrs={
                'class': 'form-control form-control-md',
                'rows': 4,
            }),
        } 
        


class DependentForm(forms.ModelForm):
    class Meta:
        model = Dependent
        fields = ['name', 'date_of_birth', 'relationship'] 
        widgets={
             'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control form-control-md datepicker-input',
                 'style': ' width: 160px;',
                 'type': 'text',
                 'placeholder': 'YYYY-MM-DD',
              }),
        }
       
       
class ReplyForm(forms.ModelForm):
    class Meta:
        model = Reply
        fields = ['content']
        widgets={
            'content': forms.Textarea(attrs={
                'class': 'form-control form-control-md',
               'rows': 4,
            }),
        }
        
        
class EditReplyForm(forms.ModelForm):
    class Meta:
        model = Reply
        fields = ['content']
        widgets={
            'content': forms.Textarea(attrs={
                'class': 'form-control form-control-md',
                'rows': 4,
            }),
        }


class SearchForm(forms.Form):
    query = forms.CharField(max_length=100, required=True)

    widgets={
            'query': forms.Textarea(attrs={
                'class': 'form-control form-control-md',
                'placeholder':'search',
                
            }),
        }  



class AddAdminForm(forms.Form):
    member = forms.ModelChoiceField(queryset=Profile.objects.none(), label='Select New Member')

    def __init__(self, *args, **kwargs):
        group = kwargs.pop('group', None)
        super(AddAdminForm, self).__init__(*args, **kwargs)
        if group:
            # Filter for members of this group who are NOT already admins
            # Get IDs of profiles that are members but not admins
            # This logic assumes GroupMembership model has is_admin field
            self.fields['member'].queryset = Profile.objects.filter(
                groupmembership__group=group,
                groupmembership__is_admin=False
            )
        else:
            self.fields['member'].queryset = Profile.objects.none()


class UploadFileForm(forms.Form):
    file = forms.FileField()       
        