from django.http import HttpResponse
from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404, redirect
from condolence.forms import *
from .models import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from chema.models import *
from wallet.models import Wallet, Transaction
from decimal import Decimal




@login_required
def create_contribution(request):
    # Common: Get User's Active Group Context & Role
    active_membership = GroupMembership.objects.filter(member=request.user.profile, is_active=True).first()
    if not active_membership:
        active_membership = GroupMembership.objects.filter(member=request.user.profile).first()
    
    if not active_membership:
        msg = "You are not a member of any group."
        messages.error(request, msg)
        return redirect('home')

    active_group = active_membership.group
    
    # Determine Permissions
    is_admin = (active_membership.is_admin or 
               active_membership.role in ['admin', 'moderator'] or
               active_group.creator == request.user or
               active_group.admin == request.user.profile)

    # Check for Explicit Mode
    mode = request.GET.get('mode', 'auto')

    # --- Scenario 1: Wallet Payment Flow (Regular User OR Admin Personal Payment) ---
    # Show if NOT admin, OR if admin specifically requested 'personal' mode
    if not is_admin or (is_admin and mode == 'personal'):
        if request.method == 'POST':
            # Regular users (and personal admin payments) should use the wallet API endpoints
            return HttpResponse("Invalid operation. Please use the payment form.", status=403)
        
        # Display Wallet Payment Form
        deceased_id = request.GET.get('deceased_id')
        deceased_name = ""
        if deceased_id:
             try: deceased_name = str(Deceased.objects.get(id=deceased_id))
             except (Deceased.DoesNotExist, ValueError): pass
             
        context = {
            'active_group': active_group,
            'deceased_id': deceased_id,
            'deceased_name': deceased_name,
        }
        return render(request, 'condolence/partials/wallet_payment_form.html', context)

    # --- Scenario 2: Admin (Manual Record Flow) ---
    if request.method == 'POST':
        form = ContributionForm(request.POST, active_group=active_group)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            deceased_member = form.cleaned_data['deceased_member']
            contributing_member = form.cleaned_data['contributing_member']
            # payment_method is handled by form save, default is fine or selected
            
            contribution = Contribution(
                group=active_group,
                amount=amount,
                contributing_member=contributing_member,
                group_admin=request.user.profile,
                deceased_member=deceased_member,
                payment_method=form.cleaned_data.get('payment_method', 'cash')
            )
            contribution.save()
            
            messages.success(request, "Contribution recorded successfully.")
            
            if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
                # Return a response that triggers page refresh
                response = HttpResponse(status=200)
                response['HX-Refresh'] = 'true'
                return response

            return redirect('contribution_detail', contribution.id)
        else:
             if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
                context = {'form': form}
                # Try to recover deceased name if it was submitted/hidden
                if 'deceased_member' in form.data:
                    try:
                        context['deceased_name'] = str(Deceased.objects.get(id=form.data['deceased_member']))
                    except (Deceased.DoesNotExist, ValueError):
                        pass
                return render(request, 'condolence/partials/contribution_form_content.html', context)

    else:
        # GET: Show Manual Form
        deceased_id = request.GET.get('deceased_id')
        contributing_member_id = request.GET.get('contributing_member')
        
        initial_data = {}
        deceased_name = None
        contributing_member_name = None
        
        # Handle deceased member pre-selection
        if deceased_id:
            initial_data['deceased_member'] = deceased_id
            try: deceased_name = str(Deceased.objects.get(id=deceased_id))
            except: pass
        
        # Handle contributing member pre-selection
        if contributing_member_id:
            initial_data['contributing_member'] = contributing_member_id
            try: contributing_member_name = str(Profile.objects.get(id=contributing_member_id))
            except: pass
            
        form = ContributionForm(initial=initial_data, active_group=active_group)
        
    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
        context = {'form': form}
        if 'deceased_name' in locals() and deceased_name:
            context['deceased_name'] = deceased_name
        if 'contributing_member_name' in locals() and contributing_member_name:
            context['contributing_member_name'] = contributing_member_name
        return render(request, 'condolence/partials/contribution_form_content.html', context)

    return render(request, 'condolence/create_contribution.html', {'form': form})



def test_form(request):
    """Test view to debug form rendering"""
    form = ContributionForm()
    return render(request, 'condolence/test_form.html', {'form': form})


def contribution_detail(request, contribution_id):
    contribution = get_object_or_404(Contribution, id=contribution_id)
    # Get the deceased members related to this contribution
    context = {
        'contribution': contribution,
        }

    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
        return render(request, 'condolence/partials/contribution_detail_modal.html', context)

    return render(request, 'condolence/contribution_detail.html', context)




@login_required
def deceased(request):
    # Get the active group for this user specifically
    active_membership = GroupMembership.objects.filter(
        member=request.user.profile, 
        is_active=True
    ).first()
    
    if not active_membership:
        # Fallback to first membership if none are marked active
        active_membership = GroupMembership.objects.filter(member=request.user.profile).first()
        
    if not active_membership:
        messages.error(request, "You are not a member of any group.")
        return redirect('home')
        
    active_group = active_membership.group
    
    # STRICT PERMISSION CHECK: Only admins and moderators
    is_manager = active_membership.is_admin or active_membership.role in ['admin', 'moderator'] or active_group.creator == request.user or active_group.admin == request.user.profile
    if not is_manager:
        messages.error(request, "Only group admins and moderators can declare members deceased.")
        return redirect('group_detail_view', active_group.id)

    if request.method == "POST":
        form = DeceasedForm(request.POST, active_group=active_group)
        if form.is_valid():
            
            deceased_obj = form.save(commit=False)
            deceased_obj.group = active_group
            deceased_obj.group_admin = request.user.profile
            deceased_obj.save()
            
            # Correct field name is 'deceased' which links to Profile
            member_profile = deceased_obj.deceased

            # LAYER 1: Global truth (only if not already set)
            if not member_profile.is_deceased:
                member_profile.is_deceased = True
                member_profile.save()

            # LAYER 2 + 3: Group-specific workflow
            # Use GroupMembership, ensuring singular get provided active_group and member_profile
            membership = GroupMembership.objects.get(
                group=active_group,
                member=member_profile
            )
            
            # Update local group status
            membership.is_deceased = True
            # membership.contribution_opened = True  # Field does not exist on GroupMembership
            membership.save()

            messages.success(request, "Group member has been marked as deceased and contributions opened.")

            # HTMX handling
            if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
                response = HttpResponse(status=200)
                response['HX-Refresh'] = 'true'
                return response

            return redirect('group_detail_view', active_group.id)

        else:
            if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
                context = {'deceased_form': form, 'active_group': active_group}
                return render(request, 'condolence/partials/deceased_modal.html', context)

    else:
        form = DeceasedForm(active_group=active_group)

    context = {'deceased_form': form, 'active_group': active_group}

    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
        return render(request, 'condolence/partials/deceased_modal.html', context)

    return render(request, 'condolence/deceased.html', context)



def toggle_deceased(request, deceased_id):
    # Get the deceased being toggled
    deceased_to_toggle = get_object_or_404(Deceased, id=deceased_id)
    
    # Toggle the deceased status
    deceased_to_toggle.contributions_open = not deceased_to_toggle.contributions_open
    deceased_to_toggle.save()

    return redirect(request.META.get('HTTP_REFERER', 'home'))



@login_required
def stop_contributions(request, deceased_id):
    # Get the Deceased instance
    deceased_obj = get_object_or_404(Deceased, pk=deceased_id)
    group = deceased_obj.group
    
    # STRICT PERMISSION CHECK: Check user's role in this specific group
    membership = GroupMembership.objects.filter(group=group, member=request.user.profile).first()
    is_manager = membership and (membership.is_admin or membership.role in ['admin', 'moderator'] or group.creator == request.user or group.admin == request.user.profile)
    
    if not is_manager:
        return HttpResponse("You do not have permission to perform this action.", status=403)

    # Call the method to stop contributions
    deceased_obj.stop_contributions()

    # Return a JSON response indicating success
    return HttpResponse('<h1>Contributions for This Deceased Member Closed</h2>')


def filter_contributions(request, deceased_id=None):
    mode = request.GET.get('mode')
    status_filter = request.GET.get('status', 'all')
    
    # Get active group context
    active_membership = GroupMembership.objects.filter(member=request.user.profile, is_active=True).first()
    if not active_membership:
        active_membership = GroupMembership.objects.filter(member=request.user.profile).first()
    
    if not active_membership:
        return HttpResponse("No active group found", status=403)
    
    active_group = active_membership.group

    # Common: Calculate Total Amount (Always needed for OOB)
    if deceased_id and deceased_id != 'all':
        # Ensure the deceased belongs to the active group!
        base_contributions = Contribution.objects.filter(deceased_member_id=deceased_id, group=active_group)
    else:
        base_contributions = Contribution.objects.filter(
            group=active_group
        )
    total_amount = base_contributions.aggregate(Sum('amount'))['amount__sum'] or 0

    # Detailed Mode Logic (When deceased is selected and mode is requested)
    if mode == 'detailed' and deceased_id and deceased_id != 'all':
        # Get the deceased object to show who this list is for
        deceased_obj = get_object_or_404(Deceased, id=deceased_id, group=active_group)
        
        # Get all members of the active group
        all_members = Profile.objects.filter(groups=active_group)
        
        # Get contributions for this deceased person, indexed by member ID
        contributions_map = {
            c.contributing_member_id: c 
            for c in base_contributions
        }
        
        members_data = []
        for member in all_members:
            contribution = contributions_map.get(member.id)
            is_paid = contribution is not None
            
            # Filter Logic
            if status_filter == 'paid' and not is_paid: continue
            if status_filter == 'unpaid' and is_paid: continue
            
            members_data.append({
                'member': member,
                'is_paid': is_paid,
                'amount': contribution.amount if contribution else 0,
                'date': contribution.contribution_date if contribution else None,
                'contribution_id': contribution.id if contribution else None
            })
            
        is_admin = active_group.is_admin(request.user)
                   
        context = {
            'members_data': members_data,
            'deceased': deceased_obj,  # Add the deceased object
            'deceased_id': deceased_id,
            'filter_status': status_filter,
            'total_amount': total_amount, # For OOB
            'is_admin': is_admin
        }
        return render(request, 'condolence/partials/member_status_list.html', context)

    # Standard List Logic
    deceased_obj = None
    if deceased_id and deceased_id != 'all':
        contributions = base_contributions.order_by('-contribution_date')
        deceased_obj = Deceased.objects.filter(id=deceased_id, group=active_group).first()
    else:
        contributions = base_contributions.order_by('-contribution_date')
        
    context = {
        'contributions': contributions,
        'total_amount': total_amount,
        'deceased_id': deceased_id,
        'deceased_member': deceased_obj,
        'show_detail_toggle': bool(deceased_id and deceased_id != 'all'), # Flag to show button
        'is_admin': active_group.is_admin(request.user)
    }
    return render(request, 'condolence/partials/contributions_list.html', context)


def search_contributions(request):
    query = request.GET.get('q', '')
    
    # Get active group context
    active_membership = GroupMembership.objects.filter(member=request.user.profile, is_active=True).first()
    if not active_membership:
        active_membership = GroupMembership.objects.filter(member=request.user.profile).first()
        
    if not active_membership:
        active_group = None
    else:
        active_group = active_membership.group

    if query and active_group:
        contributions = Contribution.objects.filter(
            Q(contributing_member__first_name__icontains=query) |
            Q(contributing_member__last_name__icontains=query) |
            Q(deceased_member__deceased__first_name__icontains=query) |
            Q(deceased_member__deceased__last_name__icontains=query) |
            Q(amount__icontains=query) 
        ).filter(
            group=active_group
        ).distinct().order_by('-contribution_date')
    else:
        contributions = Contribution.objects.none()

    total_amount = contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    is_admin = active_group.is_admin(request.user) if active_group else False
    
    context = {
        'contributions': contributions,
        'total_amount': total_amount,
        'is_search': True,
        'query': query,
        'is_admin': is_admin,
    }
    
    return render(request, 'condolence/partials/contributions_list.html', context)


@login_required
def contributions_list(request):
    """Page showing the list of contributions."""
    # Get user's active group membership
    active_membership = GroupMembership.objects.filter(
        member=request.user.profile,
        is_active=True
    ).first()
    
    if not active_membership:
        # Fallback to first membership
        active_membership = GroupMembership.objects.filter(member=request.user.profile).first()
    
    if not active_membership:
        messages.error(request, "You are not a member of any group.")
        return redirect('home')
    
    active_group = active_membership.group

    deceased_list = Deceased.objects.filter(group=active_group, contributions_open=True).annotate(
        total_raised=Sum('member_deceased__amount')
    )
    
    # Auto-select the first deceased member if available
    # Assuming standard ordering (e.g., creation order), you might want to order by '-id' or '-date'
    latest_deceased = deceased_list.last() # taking last created if id is sequential, or order by date if needed
    
    if latest_deceased:
        contributions = Contribution.objects.filter(deceased_member=latest_deceased, group=active_group).order_by('-contribution_date')
        selected_deceased_id = latest_deceased.id
        total_contributions = latest_deceased.total_raised # Use the annotated value
    else:
        contributions = Contribution.objects.none()
        selected_deceased_id = None
        total_contributions = 0
    
    is_admin = active_group.is_admin(request.user)

    context = {
        'active_group': active_group,
        'deceased': deceased_list,
        'contributions': contributions,
        'total_contributions': total_contributions,
        'selected_deceased_id': selected_deceased_id,
        'deceased_id': selected_deceased_id, # Also pass as deceased_id for consistency with partials
        'deceased_member': latest_deceased,
        'show_detail_toggle': True if selected_deceased_id else False,
        'is_admin': is_admin
    }
    return render(request, 'condolence/contributions_page.html', context)


@login_required
def manage_beneficiary(request, deceased_id):
    """View to select/update beneficiary for a deceased member"""
    deceased_obj = get_object_or_404(Deceased, pk=deceased_id)
    active_group = deceased_obj.group
    
    # Permission Check
    is_admin = active_group.is_admin(request.user)
    
    if not is_admin:
        return HttpResponse("Unauthorized", status=403)

    if request.method == 'POST':
        form = BeneficiaryForm(request.POST, instance=deceased_obj, active_group=active_group)
        if form.is_valid():
            form.save()
            messages.success(request, "Beneficiary updated successfully.")
            
            # HTMX: Close modal and refresh specific parts (or whole page for simplicity)
            if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
                 response = HttpResponse(status=204)
                 response['HX-Refresh'] = 'true'
                 return response
                 
            return redirect('contributions_list')
    else:
        form = BeneficiaryForm(instance=deceased_obj, active_group=active_group)
    
    context = {
        'form': form,
        'deceased': deceased_obj
    }
    return render(request, 'condolence/partials/beneficiary_modal.html', context)


@login_required
def disburse_funds(request, deceased_id):
    """View to transfer funds to the beneficiary"""
    deceased_obj = get_object_or_404(Deceased, pk=deceased_id)
    
    # Permission Check
    active_group = deceased_obj.group
    is_admin = active_group.is_admin(request.user)
    
    if not is_admin:
        return HttpResponse("Unauthorized", status=403)
        
    if not deceased_obj.beneficiary:
        return HttpResponse("Beneficiary not set", status=400)
        
    # if deceased_obj.funds_disbursed:
    #    return HttpResponse("Funds already disbursed", status=400)
        
    if request.method == 'GET':
        context = {
            'deceased': deceased_obj
        }
        return render(request, 'condolence/partials/disburse_funds_modal.html', context)

    # POST Handling
    try:
        amount_to_disburse = Decimal(request.POST.get('amount', '0'))
    except:
        return HttpResponse("Invalid amount", status=400)

    available_balance = deceased_obj.get_balance()
    
    if amount_to_disburse <= 0:
        messages.error(request, "Amount must be positive.")
        # Re-render modal with error? For now simple response or redirect
        if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
             response = HttpResponse(status=204) # Close modal
             response['HX-Refresh'] = 'true'
             return response
        return redirect('contributions_list')

    if amount_to_disburse > available_balance:
        return HttpResponse("Insufficient funds", status=400)

    # Create Transaction for Beneficiary (PAYOUT_RECEIVED)
    beneficiary_wallet, _ = Wallet.objects.get_or_create(
        user=deceased_obj.beneficiary.user, 
        defaults={'external_wallet_id': f"auto_{deceased_obj.beneficiary.user.phone or deceased_obj.beneficiary.user.id}"}
    )
    
    Transaction.objects.create(
        wallet=beneficiary_wallet,
        transaction_type='PAYOUT_RECEIVED',
        amount=amount_to_disburse,
        status='COMPLETED',
        destination_group=active_group,
        deceased_contribution=deceased_obj
    )
    beneficiary_wallet.recalculate_balance()
    
    deceased_obj.funds_disbursed = True 
    # deceased_obj.stop_contributions() 
    deceased_obj.save()
    
    new_balance = beneficiary_wallet.get_balance()
    messages.success(request, f"Successfully disbursed R {amount_to_disburse} to {deceased_obj.beneficiary}. New Wallet Balance: R {new_balance}")
    
    if request.headers.get('HX-Request') and not request.headers.get('HX-Boosted'):
         response = HttpResponse(status=204) # Close modal
         response['HX-Refresh'] = 'true'
         return response

    return redirect('contributions_list')
