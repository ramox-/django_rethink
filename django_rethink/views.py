# Copyright 2017 Klarna AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import rethinkdb as r
from django.views.generic.base import ContextMixin, View
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt
from django.utils.encoding import force_text
from django_rethink.connection import get_connection

class RethinkMixin(object):
    rethink_conn = None
    def get_connection(self):
        if self.rethink_conn is None:
            self.rethink_conn = get_connection()
        return self.rethink_conn

class RethinkSingleObjectMixin(ContextMixin, RethinkMixin):
    pk_url_kwarg = "id"
    slug_url_kwarg = "slug"
    pk_field = "id"
    slug_field = "slug"
    table_name = None
    queryset = None
    pk_index_name = None
    slug_index_name = None

    def get_object_qs(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()

        pk = self.kwargs.get(self.pk_url_kwarg, None)
        slug = self.kwargs.get(self.slug_url_kwarg, None)
        if pk is None and slug is None:
            raise AttributeError("Generic detail view %s must be called with "
                                 "either an object pk or a slug."
                                 % self.__class__.__name__)
        elif pk is not None:
            if self.pk_index_name:
                queryset = queryset.get_all(pk, index=self.pk_index_name)
            else:
                queryset = queryset.filter(r.row[self.pk_field] == pk)
        elif pk is None and slug is not None:
            if self.slug_index_name:
                queryset = queryset.get_all(slug, index=self.slug_index_name)
            else:
                queryset = queryset.filter(r.row[self.slug_field] == slug)
        return queryset

    def get_object(self, queryset=None):
        queryset = self.get_object_qs(queryset)

        try:
            obj = queryset.run(self.get_connection()).next()
        except r.net.DefaultCursorEmpty:
            raise Http404(_("No %(verbose_name)s found matching the query") %
                          {'verbose_name': self.table_name})

        return obj

    def get_queryset(self):
        if self.queryset is None:
            if self.table_name:
                return r.table(self.table_name)
            else:
                raise ImproperlyConfigured(
                    "%(cls)s is missing a QuerySet. Define "
                    "%(cls)s.model, %(cls)s.queryset, or override "
                    "%(cls)s.get_queryset()." % {
                        'cls': self.__class__.__name__
                    }
                )
        return self.queryset


    def get_context_data(self, **kwargs):
        """
        Insert the single object into the context dict.
        """
        context = {}
        if self.object:
            context['object'] = self.object
            context_object_name = self.get_context_object_name(self.object)
            if context_object_name:
                context[context_object_name] = self.object
        context.update(kwargs)
        return super(RethinkSingleObjectMixin, self).get_context_data(**context)

class RethinkUpdateView(RethinkSingleObjectMixin, View):
    insert_if_missing = False
    success_url = None

    def get_success_url(self):
        if self.success_url:
            return self.success_url.format(**self.object)
        else:
            raise ImproperlyConfigured(
                "No URL to redirect to. Provide a success_url.")

    def get_update_data(self):
        return self.get_request_data()

    def get_request_data(self):
        if self.request.META['CONTENT_TYPE'] == "application/json":
            return json.loads(force_text(self.request.body))
        else:
            return dict(self.request.POST)

    def post_update(self):
        pass

    def post(self, *args, **kwargs):
        conn = self.get_connection()
        update_data = self.get_update_data()
        result = self.get_object_qs().update(r.expr(update_data, nesting_depth=40)).run(conn)
        if max(result.values()) == 0:
            result = r.table(self.table_name).insert(r.expr(self.get_insert_data(update_data), nesting_depth=40)).run(conn)
        self.post_update()
        if self.request.META['CONTENT_TYPE'] == "application/json":
            return HttpResponse(json.dumps({'success': True}), content_type="application/json")
        else:
            return HttpResponseRedirect(self.get_success_url())

    def put(self, *args, **kwargs):
        return self.post(*args, **kwargs)

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(RethinkUpdateView, self).dispatch(*args, **kwargs)