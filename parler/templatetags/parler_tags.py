from django.core.urlresolvers import resolve, reverse
from django.template import Node, Library, TemplateSyntaxError
from django.utils.translation import get_language
from parler.models import TranslatableModel, TranslationDoesNotExist
from parler.utils.context import switch_language, smart_override

register = Library()


class ObjectLanguageNode(Node):
    def __init__(self, nodelist, object_var, language_var=None):
        self.nodelist = nodelist  # This name is special in the Node baseclass
        self.object_var = object_var
        self.language_var = language_var

    def render(self, context):
        # Read context data
        object = self.object_var.resolve(context)
        new_language = self.language_var.resolve(context) if self.language_var else get_language()
        if not isinstance(object, TranslatableModel):
            raise TemplateSyntaxError("Object '{0}' is not an instance of TranslableModel".format(object))

        with switch_language(object, new_language):
            # Render contents inside
            output = self.nodelist.render(context)

        return output


@register.tag
def objectlanguage(parser, token):
    """
    Template tag to switch an object language
    Example::

        {% objectlanguage object "en" %}
          {{ object.title }}
        {% endobjectlanguage %}

    A TranslatedObject is not affected by the ``{% language .. %}`` tag
    as it maintains it's own state. This tag temporary switches the object state.

    Note that using this tag is not thread-safe if the object is shared between threads.
    It temporary changes the current language of the object.
    """
    bits = token.split_contents()
    if len(bits) == 2:
        object_var = parser.compile_filter(bits[1])
        language_var = None
    elif len(bits) == 3:
        object_var = parser.compile_filter(bits[1])
        language_var = parser.compile_filter(bits[2])
    else:
        raise TemplateSyntaxError("'%s' takes one argument (object) and has one optional argument (language)" % bits[0])

    nodelist = parser.parse(('endobjectlanguage',))
    parser.delete_first_token()
    return ObjectLanguageNode(nodelist, object_var, language_var)


@register.assignment_tag(takes_context=True)
def get_translated_url(context, lang_code, object=None):
    """
    Get the proper URL for this page in a different language.

    Note that this algorithm performs a "best effect" approach to give a proper URL.
    To make sure the proper view URL is returned, add the :class:`~parler.views.ViewUrlMixin` to your view.

    Example, to build a language menu::

        <ul>
            {% for lang_code, title in LANGUAGES %}
                {% get_language_info for lang_code as lang %}
                {% get_translated_url lang_code as tr_url %}
                {% if tr_url %}<li{% if lang_code == LANGUAGE_CODE %} class="is-selected"{% endif %}><a href="{{ tr_url }}" hreflang="{{ lang_code }}">{{ lang.name_local|capfirst }}</a></li>{% endif %}
            {% endfor %}
        </ul>

    Or to inform search engines about the translated pages::

       {% for lang_code, title in LANGUAGES %}
           {% get_translated_url lang_code as tr_url %}
           {% if tr_url %}<link rel="alternate" hreflang="{{ lang_code }}" href="{{ tr_url }}" />{% endif %}
       {% endfor %}

    Note that using this tag is not thread-safe if the object is shared between threads.
    It temporary changes the current language of the view object.
    """
    view = context.get('view', None)
    if object is None:
        object = context.get('object', None)

    try:
        if view is not None:
            # Allow a view to specify what the URL should be.
            # This handles situations where the slug might be translated,
            # and gives you complete control over the results of this template tag.
            get_view_url = getattr(view, 'get_view_url', None)
            if get_view_url:
                with smart_override(lang_code):
                    return view.get_view_url()

            # Now, the "best effort" part starts.
            # See if it's a DetailView that exposes the object.
            if object is None:
                object = getattr(view, 'object', None)

        if object is not None and hasattr(object, 'get_absolute_url'):
            # There is an object, get the URL in the different language.
            # NOTE: this *assumes* that there is a detail view, not some edit view.
            # In such case, a language menu would redirect a user from the edit page
            # to a detail page; which is still way better a 404 or homepage.
            if isinstance(object, TranslatableModel):
                # Need to handle object URL translations.
                # Just using smart_override() should be enough, as a translated object
                # should use `switch_language(self)` internally before returning an URL.
                # However, it doesn't hurt to help a bit here.
                with switch_language(object, lang_code):
                    return object.get_absolute_url()
            else:
                # Always switch the language before resolving, so i18n_patterns() are supported.
                with smart_override(lang_code):
                    return object.get_absolute_url()
    except TranslationDoesNotExist:
        # Typically projects have a fallback language, so even unknown languages will return something.
        # This either means fallbacks are disabled, or the fallback language is not found!
        return ''

    # Just reverse the current URL again in a new language, and see where we end up.
    # This doesn't handle translated slugs, but will resolve to the proper view name.
    path = context['request'].path
    resolvermatch = resolve(path)
    with smart_override(lang_code):
        return reverse(resolvermatch.view_name, args=resolvermatch.args, kwargs=resolvermatch.kwargs)
