import { memo, type ReactNode } from 'react';
import './forest-backdrop.css';

/** Static, trusted SVG. Exported so non-React previews use exactly the same artwork. */
export const FOREST_BACKDROP_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" preserveAspectRatio="none" aria-hidden="true" focusable="false" class="nb-forest-backdrop__art">
  <g class="nb-backdrop-hills">
    <path class="nb-backdrop-mist nb-backdrop-wash" d="M0 785 C57 783 78 818 115 825 C173 837 197 869 253 879 C281 886 305 898 320 918 L320 1000 L0 1000Z"/>
    <path class="nb-backdrop-mist" opacity=".3" d="M0 831 C48 816 92 854 121 860 C179 871 208 914 274 925 L286 1000 L0 1000Z"/>
    <path class="nb-backdrop-mist nb-backdrop-wash" d="M1280 926 C1332 916 1352 880 1394 870 C1453 854 1493 794 1548 808 C1573 814 1583 795 1600 797 L1600 1000 L1280 1000Z"/>
    <path class="nb-backdrop-lichen" opacity=".15" d="M1380 967 C1439 938 1458 887 1498 897 C1545 911 1566 877 1600 877 L1600 1000 L1370 1000Z"/>
  </g>
  <g class="nb-backdrop-distant" opacity=".22">
    <path class="nb-backdrop-mist" d="M0 910 C8 893 1 878 13 871 C6 856 17 843 27 847 C22 831 34 827 43 834 C48 815 63 825 62 842 C81 839 89 854 81 866 C100 865 108 881 99 890 C119 887 135 909 129 923Z"/>
    <path class="nb-backdrop-mist" d="M1490 926 C1481 912 1491 902 1500 900 C1490 882 1501 869 1516 874 C1514 858 1524 850 1535 860 C1547 843 1564 853 1561 872 C1577 861 1587 877 1584 888 C1594 883 1598 892 1600 896 L1600 936Z"/>
    <path class="nb-backdrop-stroke" d="M48 895 Q45 874 51 853 M76 903 Q76 886 72 873 M1524 918 Q1531 902 1528 880 M1562 927 Q1558 908 1565 894"/>
  </g>
  <g class="nb-backdrop-moss" opacity=".38">
    <g><path class="nb-backdrop-lichen" d="M24 974 Q56 955 91 966 Q111 954 147 972 Q103 988 24 981Z"/><path class="nb-backdrop-stroke" d="M55 975 Q54 965 48 961 M58 975 Q61 962 66 958 M89 976 Q86 962 79 960 M94 976 Q98 963 106 961"/></g>
    <g><path class="nb-backdrop-mist" d="M172 989 Q193 978 225 985 Q249 975 272 990 Q222 998 172 995Z"/><path class="nb-backdrop-stroke" d="M214 989 Q211 979 206 976 M217 990 Q221 980 227 979"/></g>
    <g><path class="nb-backdrop-lichen" d="M1443 978 Q1473 963 1500 974 Q1526 959 1559 975 Q1517 992 1443 985Z"/><path class="nb-backdrop-stroke" d="M1481 980 Q1482 967 1474 963 M1486 980 Q1492 967 1498 968 M1531 979 Q1529 968 1523 966"/></g>
  </g>
</svg>`;

/** Mount beside the camera SVG, never inside its translated/scaled <g>. No hooks, IDs or DOM reads. */
export const ForestBackdrop = memo(function ForestBackdrop({ className = '' }: { className?: string }) {
  return <div className={`nb-forest-backdrop ${className}`} aria-hidden="true"
    data-od-id="forest-backdrop" dangerouslySetInnerHTML={{ __html: FOREST_BACKDROP_SVG }} />;
});

/** Existing search, legend and camera controls stay owned by the product. */
export function ForestToolbar({ search, legend, controls }: {
  search: ReactNode; legend: ReactNode; controls: ReactNode;
}) {
  return <div className="nb-forest-toolbar" data-od-id="forest-toolbar">
    <div className="nb-forest-toolbar__search" role="search" aria-label="搜索知识森林">{search}</div>
    <div className="nb-forest-toolbar__legend" role="group" aria-label="课程学习状态图例">{legend}</div>
    <div className="nb-forest-toolbar__controls">{controls}</div>
  </div>;
}
