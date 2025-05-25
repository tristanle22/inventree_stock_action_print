"""Print report every stock event"""

from plugin import InvenTreePlugin
from plugin.mixins import EventMixin, ReportMixin, SettingsMixin
from stock.models import StockItem, StockItemTracking
from report.models import ReportTemplate
from common.notifications import trigger_notification
from django.contrib.auth import get_user_model
from stock.status_codes import StockHistoryCode

from . import PLUGIN_VERSION
import logging

logger = logging.getLogger(__name__)


class StockEventReport(EventMixin, ReportMixin, SettingsMixin, InvenTreePlugin):
    """StockEventReport - custom InvenTree plugin."""

    # Plugin metadata
    TITLE = "StockEventReport"
    NAME = "StockEventReport"
    SLUG = "stockeventreport"
    DESCRIPTION = "Print report every stock event"
    VERSION = PLUGIN_VERSION

    # Additional project information
    AUTHOR = "Tristan Le"
    WEBSITE = "https://github.com/tristanle22/stock_action_print#"
    LICENSE = "MIT"

    SETTINGS = {
    'STOCK_ADD_TEMPLATE': {
        'name': 'Stock Addition Report Template',
        'description': 'Select which report template to use when stock is added',
        'model': 'report.reporttemplate',  # This makes it a model choice field
        'required': True,
    },
    'STOCK_REMOVE_TEMPLATE': {
        'name': 'Stock Removal Report Template',
        'description': 'Select which report template to use when stock is removed',
        'model': 'report.reporttemplate',  # This makes it a model choice field
        'required': True,
    },
}
    
    def wants_process_event(self, event: str) -> bool:
        """Return True if the plugin wants to process the given event."""
        return event == 'stock_stockitemtracking.created'
    
    def process_event(self, event: str, *args, **kwargs) -> None:
        """Process the provided event."""
        try:
            # Extract the stock item from the event
            stock_item: StockItem = StockItemTracking.objects.filter(pk=kwargs['id']).first().item
            if not stock_item:
                logger.warning("Could not find stock item")
                return
            
            logger.info(f"Processing quantity update for StockItem {stock_item.pk}")

            # Get the latest tracking entry
            tracking_entry = stock_item.tracking_info.order_by('-date').first()
            if not tracking_entry:
                logger.warning("No tracking entry found")
                return

            # Get the template ID based on the tracking type
            template_id = None
            if tracking_entry.tracking_type == StockHistoryCode.STOCK_ADD.value:
                template_id = self.get_setting('STOCK_ADD_TEMPLATE')
            elif tracking_entry.tracking_type == StockHistoryCode.STOCK_REMOVE.value:
                template_id = self.get_setting('STOCK_REMOVE_TEMPLATE')
            else:
                logger.info(f"Tracking type {tracking_entry.tracking_type} not handled")
                return

            if not template_id:
                logger.warning("No template configured for this action type")
                return

            try:
                # Get the actual template object
                report_template = ReportTemplate.objects.get(pk=template_id)
            except ReportTemplate.DoesNotExist:
                logger.error(f"Could not find template with ID {template_id}")
                return
            
            try:
                # Generate the report and get the output
                output = report_template.print([stock_item]).output
                if output and output.url:
                    # Build list of targets
                    targets = []
                    
                    # Add stock item owner if exists
                    if stock_item.owner:
                        targets.append(stock_item.owner)
                        
                    # Add the user who made the change if available
                    user = tracking_entry.user if tracking_entry else None
                    if user and user not in targets:
                        targets.append(user)
                    
                    # Trigger the notification
                    trigger_notification(
                        stock_item,  # The model instance that triggered the notification
                        'report.generated',  # Notification category
                        context={
                            'name': 'Stock Report Generated',
                            'message': f'A report has been generated for {stock_item.part.name}',
                            'link': output.url,
                        },
                        targets=targets if targets else None,
                        check_recent=False
                    )
                    
                    logger.info(f"Report generated and notification sent: {output.url}")
            except Exception as e:
                logger.error(f"Failed to generate report {report_template.name}: {str(e)}")
        except Exception as e:
            logger.error(f"Error processing stock quantity update event: {str(e)}")
    
    def add_report_context(self, report_instance, model_instance, request, context):
        """Add custom context data to a report rendering context."""
        
        if isinstance(model_instance, StockItem):
            # Get the latest tracking entry
            tracking_entry = model_instance.tracking_info.order_by('-date').first()
            
            if tracking_entry:
                # Add tracking information to the context
                context['tracking'] = {
                    'date': tracking_entry.date,
                    'user': tracking_entry.user.username if tracking_entry.user else 'System',
                    'type': tracking_entry.label(),  # Get the human-readable label for the tracking type
                    'notes': tracking_entry.notes,
                    'deltas': tracking_entry.deltas or {},  # Include all changes
                }
                
                # Add specific delta values for easy access in the template
                if tracking_entry.deltas:
                    context['quantity_change'] = tracking_entry.deltas.get('quantity')
                    context['previous_quantity'] = tracking_entry.deltas.get('previous_quantity')
                    context['location_change'] = tracking_entry.deltas.get('location')
                    context['status_change'] = tracking_entry.deltas.get('status')
                    
                    # Calculate total price if there's an 'added' delta
                    if 'added' in tracking_entry.deltas and model_instance.purchase_price:
                        context['total_price'] = tracking_entry.deltas['added'] * model_instance.purchase_price
                    else:
                        context['total_price'] = 0
                    
                    # Add purchase price for reference
                    context['purchase_price'] = model_instance.purchase_price if model_instance.purchase_price else 0
        
        return context

    def report_callback(self, template, instance, report, request, **kwargs):
        """Callback function called after a report is generated."""
        ...

    