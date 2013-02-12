from reding.settings import KEY_CONFIG, rclient

from flask.ext.restful import reqparse, fields, marshal_with, abort
from flask.ext import restful

from time import time
from datetime import datetime


def add_vote_arg(parser, required=False):
    parser.add_argument('vote', type=int, required=required, default=0)


def add_config_args(parser):
    for k in KEY_CONFIG:
        parser.add_argument(k, type=str)


def get_user_object_reply(object_id, user_id, vote, when):
    return {
        'object_id': object_id,
        'user_id': user_id,
        'vote': vote,
        'when': when,
    }


def get_user_key_name(**kw):
    t = "{prefix}:{subject}:{user_id}:{objects}"
    return get_key_name(t, **kw)


def get_object_key_name(**kw):
    t = "{prefix}:{objects}"
    return get_key_name(t, **kw)


def get_user_object_key_name(**kw):
    t = "{prefix}:{object}:{object_id}:{subjects}"
    return get_key_name(t, **kw)


def get_key_name(template, **kw):
    kw = dict((key, value) for (key, value) in kw.iteritems() if value)

    d = KEY_CONFIG.copy()
    d.update(kw)

    return template.format(**d)


# TODO: add tests, need 404?
# def abort_if_todo_doesnt_exist(todo_id):
    #if todo_id not in TODOS:
        #abort(404, message="Todo {} doesn't exist".format(todo_id))

object_resource_fields = {
    'votes_no': fields.Integer,
    'amount': fields.Integer,
    'average': fields.Float,
    'object_id': fields.String,
}

user_object_resource_fields = {
    'vote': fields.Integer,
    'object_id': fields.String,
    'user_id': fields.String,
    'when': fields.DateTime
}


class RedingResource(restful.Resource):

    redis = rclient
    parser_cls = reqparse.RequestParser

    def __init__(self):
        super(RedingResource, self).__init__()
        self.parser = self.parser_cls()
        add_config_args(self.parser)


class VotedListResource(RedingResource):

    @marshal_with(object_resource_fields)
    def get(self):
        amounts = self.redis.zrangebyscore(
            get_object_key_name(),
            '-inf',
            '+inf',
            withscores=True,
        )

        reply = []
        for o, a in amounts:
            n = self.redis.zcount(
                get_user_object_key_name(
                    object_id=o,
                ),
                '-inf',
                '+inf',
            )

            average = 0
            if n:
                average = a / n

            reply.append(
                dict(
                    votes_no=n,
                    average=average,
                    amount=a,
                    object_id=o,
                )
            )

        return reply


class VotedSummaryResource(RedingResource):

    @marshal_with(object_resource_fields)
    def get(self, object_id):
        add_vote_arg(self.parser)
        args = self.parser.parse_args()

        vote = args['vote']

        amount = self.redis.zscore(
            get_object_key_name(**args),
            object_id,
        )

        min_vote = '-inf'
        max_vote = '+inf'
        if vote:
            min_vote = vote
            max_vote = vote

        number = self.redis.zcount(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            min_vote,
            max_vote,
        )

        if not number:
            average = 0
            amount = 0
        elif vote:
            average = vote
            amount = vote * number
        else:
            average = amount / number

        return (
            dict(
                votes_no=number,
                average=average,
                amount=amount,
                object_id=object_id,
            )
        )


class VotingUserListResource(RedingResource):

    @marshal_with(user_object_resource_fields)
    def get(self, object_id):
        add_vote_arg(self.parser)
        args = self.parser.parse_args()

        vote = args['vote']

        min_vote = '-inf'
        max_vote = '+inf'
        if vote:
            min_vote = vote
            max_vote = vote

        votes = self.redis.zrangebyscore(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            min_vote,
            max_vote,
            withscores=True,
        )

        reply = [
            get_user_object_reply(
                object_id=object_id,
                user_id=u,
                vote=v,
                when=datetime.fromtimestamp(
                    self.redis.zscore(
                        get_user_key_name(
                            user_id=u,
                            **args
                        ),
                        object_id,
                    ),
                ),
            ) for u, v in votes
        ]

        return reply


class UserSummaryResource(RedingResource):

    @marshal_with(user_object_resource_fields)
    def get(self, user_id):
        args = self.parser.parse_args()

        votetimes = self.redis.zrangebyscore(
            get_user_key_name(
                user_id=user_id,
                **args
            ),
            '-inf',
            '+inf',
            withscores=True,
        )

        reply = [
            get_user_object_reply(
                object_id=o,
                user_id=user_id,
                vote=self.redis.zscore(
                    get_user_object_key_name(
                        object_id=o,
                        **args
                    ),
                    user_id,
                ),
                when=datetime.fromtimestamp(
                    self.redis.zscore(
                        get_user_key_name(
                            user_id=user_id,
                            **args
                        ),
                        o,
                    ),
                )
            ) for o, t in votetimes
        ]

        return reply


class VoteSummaryResource(RedingResource):

    @marshal_with(user_object_resource_fields)
    def get(self, object_id, user_id):
        args = self.parser.parse_args()

        vote = self.redis.zscore(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            user_id,
        )

        when_ts = self.redis.zscore(
            get_user_key_name(
                user_id=user_id,
                **args
            ),
            object_id,
        )

        if not (vote and when_ts):
            m = "No vote on {object_id} by {user_id}.".format(
                object_id=object_id,
                user_id=user_id
            )
            abort(404, message=m)

        return get_user_object_reply(
            object_id=object_id,
            user_id=user_id,
            vote=vote,
            when=datetime.fromtimestamp(
                when_ts,
            ),
        )

    def post(self, object_id, user_id):
        return self.put(object_id, user_id)

    @marshal_with(user_object_resource_fields)
    def put(self, object_id, user_id):
        add_vote_arg(self.parser, required=True)
        args = self.parser.parse_args()

        next_vote = args['vote']

        self._perform_correction(object_id, user_id, next_vote, args)

        self.redis.zadd(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            next_vote,
            user_id,
        )

        self.redis.zadd(
            get_user_key_name(
                user_id=user_id,
                **args
            ),
            time(),
            object_id,
        )

        return get_user_object_reply(
            object_id=object_id,
            user_id=user_id,
            vote=self.redis.zscore(
                get_user_object_key_name(
                    object_id=object_id,
                    **args
                ),
                user_id,
            ),
            when=datetime.fromtimestamp(
                self.redis.zscore(
                    get_user_key_name(
                        user_id=user_id,
                        **args
                    ),
                    object_id,
                ),
            )
        )

    def delete(self, object_id, user_id):
        args = self.parser.parse_args()

        next_vote = 0
        self._perform_correction(object_id, user_id, next_vote, args)

        self.redis.zrem(
            get_user_key_name(
                user_id=user_id,
                **args
            ),
            object_id,
        )

        self.redis.zrem(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            user_id,
        )

        return '', 204

    def _perform_correction(self, object_id, user_id, next_vote, args):
        prev_vote = self.redis.zscore(
            get_user_object_key_name(
                object_id=object_id,
                **args
            ),
            user_id,
        )

        if not prev_vote:
            prev_vote = 0

        correction = next_vote - prev_vote

        # perform vote correction in `all apps` zset
        if correction:
            self.redis.zincrby(
                get_object_key_name(**args),
                object_id,
                correction,
            )

__all__ = (
    VotedSummaryResource,
    VotedListResource,
    VotingUserListResource,
    VoteSummaryResource,
    UserSummaryResource
)
