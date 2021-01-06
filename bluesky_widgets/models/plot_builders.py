from collections import defaultdict
import functools
import itertools

import numpy

from .plot_specs import (
    FigureSpec,
    AxesSpec,
    ImageSpec,
    LineSpec,
)
from .utils import auto_label, call_or_eval, RunList, run_is_live_and_not_completed
from ..utils.dict_view import DictView


class RecentLines:
    """
    Plot y vs x for the last N runs.

    This supports plotting columns like ``"I0"`` but also Python
    expressions like ``"5 * log(I0/It)"`` and even
    ``"my_custom_function(I0)"``. See examples below. Consult
    :func:``bluesky_widgets.models.utils.construct_namespace` for details
    about the available variables.

    Parameters
    ----------
    max_runs : Integer
        Number of lines to show at once
    x : String | Callable
        Field name (e.g. "theta") or expression (e.g. "- deg2rad(theta) / 2")
        or callable with expected signature::

            f(run: BlueskyRun) -> x: Array

        Other signatures are also supported to allow for a somewhat "magical"
        usage. See examples below, and also see
        :func:`bluesky_widgets.models.utils.call_or_eval` for details and more
        examples.

    ys : List[String | Callable]
        Field name (e.g. "theta") or expression (e.g. "- deg2rad(theta) / 2")
        or callable with expected signature::

            f(run: BlueskyRun) -> y: Array

        Other signatures are also supported to allow for a somewhat "magical"
        usage. See examples below, and also see
        :func:`bluesky_widgets.models.utils.call_or_eval` for details and more
        examples.


    label_maker : Callable, optional
        Expected signature::

            f(run: BlueskyRun, y: String) -> label: String

    needs_streams : List[String], optional
        Streams referred to by x and y. Default is ``["primary"]``
    namespace : Dict, optional
        Inject additional tokens to be used in expressions for x and y
    axes : AxesSpec, optional
        If None, an axes and figure are created with default labels and titles
        derived from the ``x`` and ``y`` parameters.

    Attributes
    ----------
    max_runs : int
        Number of Runs to plot at once. This may be changed at any point.
        (Note: Increasing it will not restore any Runs that have already been
        removed, but it will allow more new Runs to be added.)
    runs : RunList[BlueskyRun]
        As runs are appended entries will be removed from the beginning of the
        last (first in, first out) so that there are at most ``max_runs``.
    pinned : Frozenset[String]
        Run uids of pinned runs.
    figure : FigureSpec
    axes : AxesSpec
    x : String | Callable
        Read-only access to x
    ys : Tuple[String | Callable]
        Read-only access to ys
    needs_streams : Tuple[String]
        Read-only access to stream names needed
    namespace : Dict
        Read-only access to user-provided namespace

    Examples
    --------

    Plot "det" vs "motor" and view it.

    >>> model = RecentLines(3, "motor", ["det"])
    >>> from bluesky_widgets.jupyter.figures import JupyterFigure
    >>> view = JupyterFigure(model.figure)
    >>> model.add_run(run)
    >>> model.add_run(another_run, pinned=True)

    Plot a mathematical transformation of the columns using any object in
    numpy. This can be given as a string expression:

    >>> model = RecentLines(3, "abs(motor)", ["-log(det)"])
    >>> model = RecentLines(3, "abs(motor)", ["pi * det"])
    >>> model = RecentLines(3, "abs(motor)", ["sqrt(det)"])

    Plot multiple lines.

    >>> model = RecentLines(3, "motor", ["log(I0/It)", "log(I0)", "log(It)"])

    Plot every tenth point.

    >>> model = RecentLines(3, "motor", ["intesnity[::10]"])

    Access data outside the "primary" stream, such as a stream name "baseline".

    >>> model = RecentLines(3, "motor", ["intensity/baseline['intensity'][0]"])

    As shown, objects from numpy can be used in expressions. You may define
    additional words, such as "savlog" for a Savitzky-Golay smoothing filter,
    by passing it a dict mapping the new word to the new object.

    >>> import scipy.signal
    >>> namespace = {"savgol": scipy.signal.savgol_filter}
    >>> model = RecentLines(3, "motor", ["savgol(intensity, 5, 2)"],
    ...                     namespace=namespace)

    Or you may pass in a function. It will be passed parameters according to
    their names.

    >>> model = RecentLines(3, "motor", [lambda intensity: savgol(intensity, 5, 2)])

    More examples of this function-based usage:

    >>> model = RecentLines(3, "abs(motor)", [lambda det: -log(det)])
    >>> model = RecentLines(3, "abs(motor)", [lambda det, pi: pi * det])
    >>> model = RecentLines(3, "abs(motor)", [lambda det, np: np.sqrt(det)])

    Custom, user-defined objects may be added in the same way, either by adding
    names to the namespace or providing the functions directly.
    """

    def __init__(
        self,
        max_runs,
        x,
        ys,
        *,
        label_maker=None,
        needs_streams=("primary",),
        namespace=None,
        axes=None,
    ):
        super().__init__()

        if label_maker is None:
            # scan_id is always generated by RunEngine but not stricter required by
            # the schema, so we fail gracefully if it is missing.

            if len(ys) > 1:

                def label_maker(run, y):
                    return (
                        f"Scan {run.metadata['start'].get('scan_id', '?')} "
                        f"{auto_label(y)}"
                    )

            else:

                def label_maker(run, y):
                    return f"Scan {run.metadata['start'].get('scan_id', '?')}"

        # Stash these and expose them as read-only properties.
        self._max_runs = int(max_runs)
        self._x = x
        if isinstance(ys, str):
            raise ValueError("`ys` must be a list of strings, not a string")
        self._ys = tuple(ys)
        self._label_maker = label_maker
        self._needs_streams = tuple(needs_streams)
        self._namespace = namespace

        self.runs = RunList()
        self._pinned = set()

        self._color_cycle = itertools.cycle(f"C{i}" for i in range(10))
        # Maps Run (uid) to set of LineSpec UUIDs.
        self._runs_to_lines = defaultdict(set)

        self.runs.events.added.connect(self._on_run_added)
        self.runs.events.removed.connect(self._on_run_removed)

        if axes is None:
            axes = AxesSpec(
                x_label=auto_label(self.x),
                y_label=", ".join(auto_label(y) for y in self.ys),
            )
            figure = FigureSpec((axes,), title=f"{axes.y_label} v {axes.x_label}")
        else:
            figure = axes.figure
        self.axes = axes
        self.figure = figure

    def _transform(self, run, x, y):
        return call_or_eval((x, y), run, self.needs_streams, self.namespace)

    def add_run(self, run, *, pinned=False):
        """
        Add a Run.

        Parameters
        ----------
        run : BlueskyRun
        pinned : Boolean
            If True, retain this Run until it is removed by the user.
        """
        if pinned:
            self._pinned.add(run.metadata["start"]["uid"])
        self.runs.append(run)

    def discard_run(self, run):
        """
        Discard a Run, including any pinned and unpinned.

        If the Run is not present, this will return silently.

        Parameters
        ----------
        run : BlueskyRun
        """
        if run in self.runs:
            self.runs.remove(run)

    def _add_lines(self, run):
        "Add a line."
        # Create a plot if we do not have one.
        # If necessary, removes runs to make room for the new one.
        self._cull_runs()

        for y in self.ys:
            label = self._label_maker(run, y)
            # If run is in progress, give it a special color so it stands out.
            if run_is_live_and_not_completed(run):
                color = "black"
                # Later, when it completes, flip the color to one from the cycle.
                run.events.completed.connect(self._on_run_complete)
            else:
                color = next(self._color_cycle)
            style = {"color": color}

            # Style pinned runs differently.
            if run.metadata["start"]["uid"] in self._pinned:
                style.update(linestyle="dashed")
                label += " (pinned)"

            func = functools.partial(self._transform, x=self.x, y=y)
            line = LineSpec(func, run, label, style)
            run_uid = run.metadata["start"]["uid"]
            self._runs_to_lines[run_uid].add(line.uuid)
            self.axes.lines.append(line)

    def _cull_runs(self):
        "Remove Runs from the beginning of self.runs to keep the length <= max_runs."
        i = 0
        while len(self.runs) > self.max_runs + len(self._pinned):
            while self.runs[i].metadata["start"]["uid"] in self._pinned:
                i += 1
            self.runs.pop(i)

    def _on_run_added(self, event):
        "When a new Run is added, draw a line or schedule it to be drawn."
        run = event.item
        # If the stream of interest is defined already, plot now.
        if set(self.needs_streams).issubset(set(list(run))):
            self._add_lines(run)
        else:
            # Otherwise, connect a callback to run when the stream of interest arrives.
            run.events.new_stream.connect(self._on_new_stream)

    def _on_run_removed(self, event):
        "Remove the line if its corresponding Run is removed."
        run_uid = event.item.metadata["start"]["uid"]
        self._pinned.discard(run_uid)
        line_uuids = self._runs_to_lines.pop(run_uid)
        for line_uuid in line_uuids:
            try:
                line = self.axes.by_uuid[line_uuid]
            except KeyError:
                # The LineSpec was externally removed from the AxesSpec.
                continue
            self.axes.lines.remove(line)

    def _on_new_stream(self, event):
        "This callback runs whenever BlueskyRun has a new stream."
        if set(self.needs_streams).issubset(set(list(event.run))):
            self._add_lines(event.run)
            event.run.events.new_stream.disconnect(self._on_new_stream)

    def _on_run_complete(self, event):
        "When a run completes, update the color from back to a color."
        run_uid = event.run.metadata["start"]["uid"]
        try:
            line_uuids = self._runs_to_lines[run_uid]
        except KeyError:
            # The Run has been removed before the Run completed.
            return
        for line_uuid in line_uuids:
            try:
                line = self.axes.by_uuid[line_uuid]
            except KeyError:
                # The LineSpec was externally removed from the AxesSpec.
                continue
            line.style.update({"color": next(self._color_cycle)})

    @property
    def max_runs(self):
        return self._max_runs

    @max_runs.setter
    def max_runs(self, value):
        self._max_runs = value
        self._cull_runs()

    # Read-only properties so that these settings are inspectable, but not
    # changeable.

    @property
    def x(self):
        return self._x

    @property
    def ys(self):
        return self._ys

    @property
    def needs_streams(self):
        return self._needs_streams

    @property
    def namespace(self):
        return DictView(self._namespace or {})

    @property
    def pinned(self):
        return frozenset(self._pinned)


class Image:
    """
    Plot an image from a Run.

    By default, higher-dimensional data is handled by repeatedly averaging over
    the leading dimension until there are only two dimensions.

    Parameters
    ----------

    field : string
        Field name or expression
    label_maker : Callable, optional
        Expected signature::

            f(run: BlueskyRun, y: String) -> label: String

    needs_streams : List[String], optional
        Streams referred to by field. Default is ``["primary"]``
    namespace : Dict, optional
        Inject additional tokens to be used in expressions for x and y
    axes : AxesSpec, optional
        If None, an axes and figure are created with default labels and titles
        derived from the ``x`` and ``y`` parameters.

    Attributes
    ----------
    run : BlueskyRun
        The currently-viewed Run
    figure : FigureSpec
    axes : AxesSpec
    field : String
        Read-only access to field or expression
    needs_streams : List[String], optional
        Read-only access to streams referred to by field.
    namespace : Dict, optional
        Read-only access to user-provided namespace

    Examples
    --------
    >>> model = Images("ccd")
    >>> from bluesky_widgets.jupyter.figures import JupyterFigure
    >>> view = JupyterFigure(model.figure)
    >>> model.run = run
    """

    # TODO: fix x and y limits here

    def __init__(
        self,
        field,
        *,
        label_maker=None,
        needs_streams=("primary",),
        namespace=None,
        axes=None,
    ):
        super().__init__()

        if label_maker is None:
            # scan_id is always generated by RunEngine but not stricter required by
            # the schema, so we fail gracefully if it is missing.

            def label_maker(run, field):
                md = self.run.metadata["start"]
                return (
                    f"Scan ID {md.get('scan_id', '?')}   UID {md['uid'][:8]}   "
                    f"{auto_label(field)}"
                )

        self._label_maker = label_maker

        # Stash these and expose them as read-only properties.
        self._field = field
        self._needs_streams = needs_streams
        self._namespace = namespace

        self._run = None

        if axes is None:
            axes = AxesSpec()
            figure = FigureSpec((axes,), title="")
        else:
            figure = axes.figure
        self.axes = axes
        self.figure = figure

    @property
    def run(self):
        return self._run

    @run.setter
    def run(self, value):
        self._run = value
        self.axes.images.clear()
        if self._run is not None:
            self._add_image()

    def _add_image(self):
        func = functools.partial(self._transform, field=self.field)
        image = ImageSpec(func, self.run, label=self.field)
        array_shape = self.run.primary.read()[self.field].shape
        self.axes.images.append(image)
        self.axes.title = self._label_maker(self.run, self.field)
        # By default, pixels center on integer coordinates ranging from 0 to
        # columns-1 horizontally and 0 to rows-1 vertically.
        # In order to see entire pixels, we set lower limits to -0.5
        # and upper limits to columns-0.5 horizontally and rows-0.5 vertically
        # if limits aren't specifically set.
        if self.axes.x_limits is None:
            self.axes.x_limits = (-0.5, array_shape[-1]-0.5)
        if self.axes.y_limits is None:
            self.axes.y_limits = (-0.5, array_shape[-2]-0.5)
        # TODO Set axes x, y from xarray dims

    def _transform(self, run, field):
        (data,) = numpy.asarray(
            call_or_eval((field,), run, self.needs_streams, self.namespace)
        )
        # If the data is more than 2D, take the middle slice from the leading
        # axis until there are only two axes.
        while data.ndim > 2:
            middle = data.shape[0] // 2
            data = data[middle]
        return data

    @property
    def needs_streams(self):
        return self._needs_streams

    @property
    def namespace(self):
        return DictView(self._namespace or {})

    @property
    def field(self):
        return self._field


class RasteredImage:
    """
    Plot a rastered image from a Run.

    Parameters
    ----------

    field : string
        Field name or expression
    shape : Tuple[Integer]
        The (row, col) shape of the raster
    label_maker : Callable, optional
        Expected signature::

            f(run: BlueskyRun, y: String) -> label: String

    needs_streams : List[String], optional
        Streams referred to by field. Default is ``["primary"]``
    namespace : Dict, optional
        Inject additional tokens to be used in expressions for x and y
    axes : AxesSpec, optional
        If None, an axes and figure are created with default labels and titles
        derived from the ``x`` and ``y`` parameters.
    clim : Tuple, optional
        The color limits
    cmap : String or Colormap, optional
        The color map to use
    extent : scalars (left, right, bottom, top), optional
        Passed through to :meth:`matplotlib.axes.Axes.imshow`
    x_positive : String, optional
        Defines the positive direction of the x axis, takes the values 'right'
        (default) or 'left'.
    y_positive : String, optional
        Defines the positive direction of the y axis, takes the values 'up'
        (default) or 'down'.

    Attributes
    ----------
    run : BlueskyRun
        The currently-viewed Run
    figure : FigureSpec
    axes : AxesSpec
    field : String
        Read-only access to field or expression
    needs_streams : List[String], optional
        Read-only access to streams referred to by field.
    namespace : Dict, optional
        Read-only access to user-provided namespace

    Examples
    --------
    >>> model = Images("ccd")
    >>> from bluesky_widgets.jupyter.figures import JupyterFigure
    >>> view = JupyterFigure(model.figure)
    >>> model.run = run
    """

    def __init__(
        self,
        field,
        shape,
        *,
        label_maker=None,
        needs_streams=("primary",),
        namespace=None,
        axes=None,
        clim=None,
        cmap='viridis',
        extent=None,
        x_positive='right',
        y_positive='up',
    ):
        super().__init__()

        if label_maker is None:
            # scan_id is always generated by RunEngine but not stricter required by
            # the schema, so we fail gracefully if it is missing.

            def label_maker(run, field):
                md = self.run.metadata["start"]
                return (
                    f"Scan ID {md.get('scan_id', '?')}   UID {md['uid'][:8]}   {field}"
                )

        self._label_maker = label_maker

        # Stash these and expose them as read-only properties.
        self._field = field
        self._shape = shape
        self._needs_streams = needs_streams
        self._namespace = namespace

        self._run = None

        if axes is None:
            axes = AxesSpec(aspect="equal")
            figure = FigureSpec((axes,), title="")
        else:
            figure = axes.figure
        self.axes = axes
        self._clim = clim
        self._cmap = cmap
        self._extent = extent
        self._x_positive = x_positive
        self._y_positive = y_positive
        self.figure = figure

    @property
    def cmap(self):
        return self._cmap

    @cmap.setter
    def cmap(self, value):
        self._cmap = value
        for i in self.axes.images:
            i.style.update({'cmap': value})

    @property
    def clim(self):
        return self._clim

    @clim.setter
    def clim(self, value):
        self._clim = value
        for i in self.axes.images:
            i.style.update({'clim': value})

    @property
    def extent(self):
        return self._extent

    @extent.setter
    def extent(self, value):
        self._extent = value
        for i in self.axes.images:
            i.style.update({'extent': value})

    @property
    def x_positive(self):
        xmin, xmax = self.axes.x_limits
        if xmin > xmax:
            self._x_positive = 'left'
        else:
            self._x_positive = 'right'
        return self._x_positive

    @x_positive.setter
    def x_positive(self, value):
        if value not in ['right', 'left']:
            raise ValueError('x_positive must be "right" or "left"')
        self._x_positive = value
        xmin, xmax = self.axes.x_limits
        if ((xmin > xmax and self._x_positive == 'right') or
                (xmax > xmin and self._x_positive == 'left')):
            self.axes.x_limits = (xmax, xmin)
        elif ((xmax >= xmin and self._x_positive == 'right') or
                (xmin >= xmax and self._x_positive == 'left')):
            self.axes.x_limits = (xmin, xmax)
            self._x_positive = value

    @property
    def y_positive(self):
        ymin, ymax = self.axes.y_limits
        if ymin > ymax:
            self._y_positive = 'down'
        else:
            self._y_positive = 'up'
        return self._y_positive

    @y_positive.setter
    def y_positive(self, value):
        if value not in ['up', 'down']:
            raise ValueError('y_positive must be "up" or "down"')
        self._y_positive = value
        ymin, ymax = self.axes.y_limits
        if ((ymin > ymax and self._y_positive == 'up') or
                (ymax > ymin and self._y_positive == 'down')):
            self.axes.y_limits = (ymax, ymin)
        elif ((ymax >= ymin and self._y_positive == 'up') or
                (ymin >= ymax and self._y_positive == 'down')):
            self.axes.y_limits = (ymin, ymax)
            self._y_positive = value

    @property
    def run(self):
        return self._run

    @run.setter
    def run(self, value):
        self._run = value
        self.axes.images.clear()
        if self._run is not None:
            self._add_image()

    def _add_image(self):
        func = functools.partial(self._transform, field=self.field)
        style = {'cmap': self._cmap, 'clim': self._clim, 'extent': self._extent}
        image = ImageSpec(func, self.run, label=self.field, style=style)
        md = self.run.metadata["start"]
        self.axes.images.append(image)
        self.axes.title = self._label_maker(self.run, self.field)
        self.axes.x_label = md["motors"][1]
        self.axes.y_label = md["motors"][0]
        # By default, pixels center on integer coordinates ranging from 0 to
        # columns-1 horizontally and 0 to rows-1 vertically.
        # In order to see entire pixels, we set lower limits to -0.5
        # and upper limits to columns-0.5 horizontally and rows-0.5 vertically
        # if limits aren't specifically set.
        if self.axes.x_limits is None and self._x_positive == 'right':
            self.axes.x_limits = (-0.5, md["shape"][1]-0.5)
        elif self.axes.x_limits is None and self._x_positive == 'left':
            self.axes.x_limits = (md["shape"][1]-0.5, -0.5)
        if self.axes.y_limits is None and self._y_positive == 'up':
            self.axes.y_limits = (-0.5, md["shape"][0]-0.5)
        elif self.axes.y_limits is None and self._y_positive == 'down':
            self.axes.y_limits = (md["shape"][0]-0.5, -0.5)

    def _transform(self, run, field):
        i_data = numpy.ones(self._shape) * numpy.nan
        (data,) = numpy.asarray(
            call_or_eval((field,), run, self.needs_streams, self.namespace)
        )
        snaking = self.run.metadata["start"]["snaking"]
        for i in range(len(data)):
            pos = list(numpy.unravel_index(i, self._shape))
            if snaking[1] and (pos[0] % 2):
                pos[1] = self._shape[1] - pos[1] - 1
            pos = tuple(pos)
            i_data[pos] = data[i]

        return i_data

    @property
    def needs_streams(self):
        return self._needs_streams

    @property
    def namespace(self):
        return DictView(self._namespace or {})

    @property
    def field(self):
        return self._field

    @property
    def shape(self):
        return self._shape
